# isbi-2012

Image Segmentation Techniques on the ISBI 2012 dataset: http://brainiac2.mit.edu/isbi_challenge/

## Results

- 3/11/17:
    - Rand score ~0.9571, information score ~0.9821.
    - [Commit](https://github.com/alexklibisz/isbi-2012/commit/17fcc3edda94611bf0dd6edb8765fa7ceded11ca)
    - [Submission](http://brainiac2.mit.edu/isbi_challenge/content/unet-256x256-tiles-re-seeding-each-batch)
    - Re-seeding the RNG before every new batch for both training and validation gave the best information score so far. Didn't train this network for very long, so hopefully more training will improve the rand score.

- 3/11/17:
    - Rand score ~0.9641, information score ~0.9805.
    - [Commit](https://github.com/alexklibisz/isbi-2012/commit/88c2434e6066a6cbd8e8f36e0166108e30660dfe)
    - [Submission](http://brainiac2.mit.edu/isbi_challenge/content/unet-256x256-tiles-using-all-30-images-tv)
    - Using all 30 images for both training and validation gave the best rand score so far, but just barely.

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
