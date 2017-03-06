from skimage.filters import gaussian
from skimage.util import random_noise
import numpy as np
import random

def random_transforms(items, nb_min=0, nb_max=6):

    all_transforms = [
        lambda x: np.fliplr(x),
        lambda x: np.flipud(x),
        lambda x: np.rot90(x, 1),
        lambda x: np.rot90(x, 2),
        lambda x: np.rot90(x, 3),
        lambda x: gaussian(x, sigma=1),
        lambda x: gaussian(x, sigma=2),
        lambda x: random_noise(x)
    ]

    n = random.randint(nb_min, nb_max)
    transforms = random.sample(all_transforms, n)
    items_t = [item.copy() for item in items]
    for transform in transforms:
        items_t = [transform(item) for item in items_t]
    return items_t