# Unet implementation based on https://github.com/jocicmarko/ultrasound-nerve-segmentation
# Major changes:
# - Downsizing the images to 128x128 and then resizing back to 512x512 for submission.
# - Added stand-alone activation layers and batch normalization after each of them.
from itertools import cycle
from keras.models import Model, load_model
from keras.layers import Input, merge, Convolution2D, MaxPooling2D, UpSampling2D, BatchNormalization, Activation, Flatten, Reshape, Lambda, Dropout
from keras.optimizers import Adam
from keras.callbacks import ModelCheckpoint, ReduceLROnPlateau
from keras.utils.np_utils import to_categorical
from skimage.transform import resize
import argparse
import keras.backend as K
import logging
import numpy as np
import os
import pickle
import tifffile as tiff

import sys;
sys.path.append('.')
from src.utils.runtime import funcname, gpu_selection
from src.utils.model import dice_coef, fmeasure_onehot, KerasHistoryPlotCallback, KerasSimpleLoggerCallback, \
    tru_pos, tru_neg, fls_pos, fls_neg, precision_onehot, recall_onehot, jaccard_coef
from src.utils.data import random_transforms
from src.utils.multi_gpu import  make_parallel

class UNet():

    def __init__(self):

        self.config = {
            'checkpoint_path_net': None,
            'checkpoint_path_model': None,
            'checkpoint_path_history': None,
            'data_path': 'data',
            'img_shape': (512, 512),
            'input_shape': (128, 128, 1),       # Row dimension has to be a power of 2.
            'output_shape': (128, 128, 1),
            'output_shape_onehot': (128, 128, 2),
            'prop_trn': 24. / 30.,
            'prop_val': 6. / 30.,
            'montage_trn_shape': (4,6),
            'montage_val_shape': (2,3),
            'transform_train': False,
            'batch_size': 64,
            'nb_epoch': 25,
            'seed': 865,
            'nb_gpu': 1
        }

        self.net = None
        self.imgs_montage_trn = None
        self.msks_montage_trn = None
        self.imgs_montage_val = None
        self.msks_montage_val = None
        self.history = None

        return

    @property
    def checkpoint_name(self):
        return 'checkpoints/unet_jocic_%d' % self.config['input_shape'][0]

    def load_data(self):

        logger = logging.getLogger(funcname())

        logger.info('Reading images from %s.' % self.config['data_path'])
        imgs = tiff.imread('%s/train-volume.tif' % self.config['data_path'])
        msks = tiff.imread('%s/train-labels.tif' % self.config['data_path']).round()

        H, W = self.config['img_shape']

        logger.info('Combining images and masks into montages.')
        nb_trn = int(len(imgs) * self.config['prop_trn'])
        imgs_trn, msks_trn = imgs[:nb_trn], msks[:nb_trn]
        nb_row, nb_col = self.config['montage_trn_shape']
        assert nb_row * nb_col == len(imgs_trn) == len(msks_trn)
        self.imgs_montage_trn = np.empty((nb_row * H, nb_col * W))
        self.msks_montage_trn = np.empty((nb_row * H, nb_col * W))
        imgs_trn, msks_trn = iter(imgs_trn), iter(msks_trn)
        for y0 in range(0, nb_row * H, H):
            for x0 in range(0, nb_col * W, W):
                y1, x1 = y0 + H, x0 + W
                self.imgs_montage_trn[y0:y1, x0:x1] = next(imgs_trn)
                self.msks_montage_trn[y0:y1, x0:x1] = next(msks_trn)

        logger.info('Combining validation images and masks into montages')
        imgs_val, msks_val = imgs[nb_trn:], msks[nb_trn:]
        nb_row, nb_col = self.config['montage_val_shape']
        assert nb_row * nb_col == len(imgs_val) == len(msks_val)
        self.imgs_montage_val = np.empty((nb_row * H, nb_col * W))
        self.msks_montage_val = np.empty((nb_row * H, nb_col * W))
        imgs_val, msks_val = iter(imgs_val), iter(msks_val)
        for y0 in range(0, nb_row * H, H):
            for x0 in range(0, nb_col * W, W):
                y1, x1 = y0 + H, x0 + W
                self.imgs_montage_val[y0:y1, x0:x1] = next(imgs_val)
                self.msks_montage_val[y0:y1, x0:x1] = next(msks_val)

        return

    def batch_gen(self, imgs, msks, batch_size, transform=False):

        logger = logging.getLogger(funcname())

        if msks is None:
            msks = np.zeros(imgs.shape)
        else:
            msks = msks.astype('float32') / np.max(msks)
            assert np.min(msks) == 0 and np.max(msks) == 1, "Masks should be in [0,1]."
            assert len(np.unique(msks)) == 2, "Masks should be binary."

        X_batch = np.empty((batch_size,) + self.config['input_shape'])
        Y_batch = np.empty((batch_size,) + self.config['output_shape'])

        H, W = imgs.shape
        wdw_H, wdw_W, _ = self.config['input_shape']

        for batch_idx in range(batch_size):

            # Pick a random window to sample.
            y0, x0 = np.random.randint(0, H - wdw_H), np.random.randint(0, W - wdw_W)
            y1, x1 = y0 + wdw_H, x0 + wdw_W

            img_wdw = imgs[y0:y1, x0:x1]
            msk_wdw = msks[y0:y1, x0:x1]

            if transform:
                [img_wdw, msk_wdw] = random_transforms([img_wdw, msk_wdw])

            X_batch[batch_idx] = img_wdw.reshape(self.config['input_shape'])
            Y_batch[batch_idx] = msk_wdw.reshape(self.config['output_shape'])

        X_batch = X_batch - np.min(X_batch)
        X_batch = X_batch / np.max(X_batch)
        X_batch = X_batch * 2 - 1
        assert np.min(X_batch) == -1 and np.max(X_batch) == 1, "X_batch should be in [-1,1]."

        yield (X_batch, Y_batch)

    def compile(self):

        K.set_image_dim_ordering('tf')

        inputs = Input(shape=self.config['input_shape'])

        conv1 = Convolution2D(32, 3, 3, activation='linear', border_mode='same')(inputs)
        # conv1 = BatchNormalization(momentum=0.99)(conv1)
        conv1 = Activation('relu')(conv1)
        conv1 = Convolution2D(32, 3, 3, activation='linear', border_mode='same')(conv1)
        # conv1 = BatchNormalization(momentum=0.99)(conv1)
        conv1 = Activation('relu')(conv1)
        # conv1 = Dropout(0.2)(conv1)
        pool1 = MaxPooling2D(pool_size=(2, 2))(conv1)

        conv2 = Convolution2D(64, 3, 3, activation='linear', border_mode='same')(pool1)
        # conv2 = BatchNormalization(momentum=0.99)(conv2)
        conv2 = Activation('relu')(conv2)
        conv2 = Convolution2D(64, 3, 3, activation='linear', border_mode='same')(conv2)
        # conv2 = BatchNormalization(momentum=0.99)(conv2)
        conv2 = Activation('relu')(conv2)
        # conv2 = Dropout(0.2)(conv2)
        pool2 = MaxPooling2D(pool_size=(2, 2))(conv2)

        conv3 = Convolution2D(128, 3, 3, activation='linear', border_mode='same')(pool2)
        # conv3 = BatchNormalization(momentum=0.99)(conv3)
        conv3 = Activation('relu')(conv3)
        conv3 = Convolution2D(128, 3, 3, activation='linear', border_mode='same')(conv3)
        # conv3 = BatchNormalization(momentum=0.99)(conv3)
        conv3 = Activation('relu')(conv3)
        # conv3 = Dropout(0.2)(conv3)
        pool3 = MaxPooling2D(pool_size=(2, 2))(conv3)

        conv4 = Convolution2D(256, 3, 3, activation='linear', border_mode='same')(pool3)
        # conv4 = BatchNormalization(momentum=0.99)(conv4)
        conv4 = Activation('relu')(conv4)
        conv4 = Convolution2D(256, 3, 3, activation='linear', border_mode='same')(conv4)
        # conv4 = BatchNormalization(momentum=0.99)(conv4)
        conv4 = Activation('relu')(conv4)
        # conv4 = Dropout(0.2)(conv4)
        pool4 = MaxPooling2D(pool_size=(2, 2))(conv4)

        conv5 = Convolution2D(512, 3, 3, activation='linear', border_mode='same')(pool4)
        # conv5 = BatchNormalization(momentum=0.99)(conv5)
        conv5 = Activation('relu')(conv5)
        conv5 = Convolution2D(512, 3, 3, activation='linear', border_mode='same')(conv5)
        # conv5 = BatchNormalization(momentum=0.99)(conv5)
        conv5 = Activation('relu')(conv5)
        # conv5 = Dropout(0.2)(conv5)

        up6 = merge([UpSampling2D(size=(2, 2))(conv5), conv4], mode='concat', concat_axis=3)
        conv6 = Convolution2D(256, 3, 3, activation='linear', border_mode='same')(up6)
        # conv6 = BatchNormalization(momentum=0.99)(conv6)
        conv6 = Activation('relu')(conv6)
        conv6 = Convolution2D(256, 3, 3, activation='linear', border_mode='same')(conv6)
        # conv6 = BatchNormalization(momentum=0.99)(conv6)
        conv6 = Activation('relu')(conv6)
        # conv6 = Dropout(0.2)(conv6)

        up7 = merge([UpSampling2D(size=(2, 2))(conv6), conv3], mode='concat', concat_axis=3)
        conv7 = Convolution2D(128, 3, 3, activation='linear', border_mode='same')(up7)
        # conv7 = BatchNormalization(momentum=0.99)(conv7)
        conv7 = Activation('relu')(conv7)
        conv7 = Convolution2D(128, 3, 3, activation='linear', border_mode='same')(conv7)
        # conv7 = BatchNormalization(momentum=0.99)(conv7)
        conv7 = Activation('relu')(conv7)
        # conv7 = Dropout(0.2)(conv7)

        up8 = merge([UpSampling2D(size=(2, 2))(conv7), conv2], mode='concat', concat_axis=3)
        conv8 = Convolution2D(64, 3, 3, activation='linear', border_mode='same')(up8)
        # conv8 = BatchNormalization(momentum=0.99)(conv8)
        conv8 = Activation('relu')(conv8)
        conv8 = Convolution2D(64, 3, 3, activation='linear', border_mode='same')(conv8)
        # conv8 = BatchNormalization(momentum=0.99)(conv8)
        conv8 = Activation('relu')(conv8)
        # conv8 = Dropout(0.2)(conv8)

        up9 = merge([UpSampling2D(size=(2, 2))(conv8), conv1], mode='concat', concat_axis=3)
        conv9 = Convolution2D(32, 3, 3, activation='linear', border_mode='same')(up9)
        # conv9 = BatchNormalization(momentum=0.99)(conv9)
        conv9 = Activation('relu')(conv9)
        conv9 = Convolution2D(32, 3, 3, activation='linear', border_mode='same')(conv9)
        # conv9 = BatchNormalization(momentum=0.99)(conv9)
        conv9 = Activation('relu')(conv9)
        # conv9 = Dropout(0.2)(conv9)

        conv10 = Convolution2D(2, 1, 1, activation='linear')(conv9)
        conv10 = BatchNormalization(momentum=0.99)(conv10)

        output = Flatten()(conv10)
        H,W,D = self.config['output_shape_onehot']
        output = Reshape((H*W,D))(output)
        output = Activation('softmax')(output)
        output = Reshape(self.config['output_shape_onehot'])(output)

        # Slicing off the softmax probability of having a positive sample.
        # This allows you to use the regular keras metrics and avoid all the np.argmax() calls.
        def probability_positive(onehot):
            return onehot[:,:,:,1]
        output = Lambda(probability_positive)(output)
        output = Reshape(self.config['output_shape'])(output)

        self.net = Model(input=inputs, output=output)
        self.net.compile(optimizer=Adam(), loss='binary_crossentropy',
                         metrics=['fmeasure', 'precision', 'recall', dice_coef])

        return

    def train(self, notebook=False):

        logger = logging.getLogger(funcname())

        gen_trn = cycle(self.batch_gen(imgs=self.msks_montage_trn, msks=self.msks_montage_trn,
                                       batch_size=self.config['batch_size'], transform=self.config['transform_train']))
        gen_val = cycle(self.batch_gen(imgs=self.msks_montage_val, msks=self.msks_montage_val,
                                       batch_size=self.config['batch_size']))

        callbacks = []

        callbacks.append(ReduceLROnPlateau(monitor='val_loss', factor=0.1, patience=5, cooldown=3, min_lr=1e-6, verbose=1))

        if self.config['checkpoint_path_net']:
            callbacks.append(ModelCheckpoint(self.config['checkpoint_path_net'], monitor='val_loss', save_best_only=True))

        if notebook:
            callbacks.append(KerasSimpleLoggerCallback())
            callbacks.append(KerasHistoryPlotCallback())
        else:
            history_plot_cb = KerasHistoryPlotCallback()
            history_plot_cb.file_name = self.checkpoint_name + '.history.png'
            callbacks.append(history_plot_cb)

        logger.info('Training for %d epochs.' % self.config['nb_epoch'])

        np.random.seed(self.config['seed'])

        result = self.net.fit_generator(
            nb_epoch=self.config['nb_epoch'],
            samples_per_epoch=self.config['batch_size'] * 50,
            generator=gen_trn,
            nb_val_samples=self.config['batch_size'] * 30,
            validation_data=gen_val,
            initial_epoch=0,
            callbacks=callbacks,
            class_weight='auto',
            verbose=int(notebook==False)
        )

        self.history = result.history

        if self.config['checkpoint_path_history'] != None:
            logger.info('Saving history to %s.' % self.config['checkpoint_path_history'])
            f = open(self.config['checkpoint_path_history'], 'wb')
            pickle.dump(self.history, f)
            f.close()

        return

    def save(self):
        logger = logging.getLogger(funcname())

        if self.config['checkpoint_path_model']:
            logger.info('Saving model to %s.' % self.config['checkpoint_path_model'])
            payload = (self.config)
            f = open(self.config['checkpoint_path_model'], 'wb')
            pickle.dump(payload, f)
            f.close()

        return

    def load(self, checkpoint_path):
        f = open(checkpoint_path, 'rb')
        (config) = pickle.load(f)
        f.close()
        self.config = config
        return

def train(args):

    logger = logging.getLogger(funcname())

    model = UNet()
    model.config['checkpoint_path_net'] = args['net'] if args['net'] != None else model.checkpoint_name + '.net'
    model.config['checkpoint_path_model'] = model.checkpoint_name + '.model'
    model.config['checkpoint_path_history'] = model.checkpoint_name + '.history'
    model.config['transform_train'] = True
    model.config['nb_epoch'] = 15
    model.load_data()
    model.compile()
    model.net.summary()
    if os.path.exists(model.config['checkpoint_path_net']):
        logger.info('Loading saved weights from %s.' % model.config['checkpoint_path_net'])
        model.net.load_weights(model.config['checkpoint_path_net'])
    model.train()
    model.save()
    return

def submit(args):
    logger = logging.getLogger(funcname())

    model = UNet()
    model.config['checkpoint_path_net'] = args['net'] if args['net'] != None else model.checkpoint_name + '.net'
    model.compile()
    model.net.summary()
    if os.path.exists(model.config['checkpoint_path_net']):
        logger.info('Loading saved weights from %s.' % model.config['checkpoint_path_net'])
        model.net.load_weights(model.config['checkpoint_path_net'])

    logger.info('Loading training images...')
    model.load_data()

    logger.info('Loading testing images...')
    imgs = tiff.imread('data/test-volume.tif')

    logger.info('Converting to batch...')
    data_gen = model.batch_gen(imgs=imgs, msks=None, batch_size=len(imgs))
    imgs_batch, _ = next(data_gen)

    logger.info('Making predictions on batch...')
    prds_batch = model.net.predict(imgs_batch)

    logger.info('Resizing predictions %s -> %s...' % (str(prds_batch.shape), str(imgs.shape)))
    # prds_batch = np.array([np.argmax(p, axis=2) * 1.0 for p in prds_batch])
    prds_batch = np.array([resize(p, imgs.shape[1:]) for p in prds_batch])
    prds_batch = prds_batch.reshape(imgs.shape).astype('float32')

    logger.info('Saving full size predictions...')
    tiff.imsave(model.checkpoint_name + '.submission.tif', prds_batch)
    logger.info('Done - saved file to %s.' % model.checkpoint_name + '.submission.tif')

def main():

    logging.basicConfig(level=logging.INFO)

    gpu_selection()

    prs = argparse.ArgumentParser()
    prs.add_argument('--train', help='train', action='store_true')
    prs.add_argument('--submit', help='submit', action='store_true')
    prs.add_argument('--net', help='path to network weights', type=str)
    args = vars(prs.parse_args())

    if args['train']:
        train(args)

    elif args['submit']:
        submit(args)



if __name__ == "__main__":
    main()
