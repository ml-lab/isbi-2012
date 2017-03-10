# isbi-2012

Image Segmentation Techniques on the ISBI 2012 dataset: http://brainiac2.mit.edu/isbi_challenge/

## Results

- 3/9/17:
    - Rand score ~0.9511, information score ~0.9805, would have made it on the leaderboard but it was worse than my prior submission.
    - [Commit](https://github.com/alexklibisz/isbi-2012/commit/5f8b559a7fb4e9cce4548318a8cecac7b318962e)
    - [Submission](http://brainiac2.mit.edu/isbi_challenge/content/unet-256x256-tiles-loss-010-after-97x2048-epochs) 
    - Most significant difference is that I trained on all the images and validated with 9 images. I trained longer and got the loss lower than on the previous submission, so this leads me to believe there must have been a little overfitting.

- 3/8/17: 
	- Rand score ~0.9637, information score ~0.9814, ~30th place.
	- UNet based on [JocicMarko example](https://github.com/jocicmarko/ultrasound-nerve-segmentation), sampling 256x256 tiles from a montage of images.
	- [Commit](https://github.com/alexklibisz/isbi-2012/blob/054dabe7900c51b535116c3661362e223f0bee73/src/models/unet_jocic.py)
	- [Submission](http://brainiac2.mit.edu/isbi_challenge/content/unet-256x256-tiles)
	- The biggest difference seems to have been using the `he_normal` initialization for all of the convolutional layers, [inspired by this blog post](https://obilaniu6266h16.wordpress.com/2016/04/12/keras-he-adam-breakthrough/).
