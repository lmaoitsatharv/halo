# Halo word-timing model: data notice

`halo/word_model_weights.py` holds the weights of a small model that Halo uses only when **Learn word timing from playback** is switched on. The weights contain no audio and no lyrics.

The model was trained by the Halo project on:

- **LibriSpeech** (Panayotov, Chen, Povey and Khudanpur), CC BY 4.0.
- **Slakh** (Manilow, Wichern, Seetharaman and Le Roux), CC BY 4.0.
- **Groove MIDI Dataset** (Gillick, Roberts, Engel, Eck and Bamman), CC BY 4.0.

It was then fine-tuned on sung sections from:

- **MUSDB18** (Rafii, Liutkus, Stöter, Mimilakis and Bittner), https://sigsep.github.io/datasets/musdb.html. The dataset is provided for educational purposes and must not be used for any commercial purpose without the permission of the copyright holders of its tracks.
- **MUSDB18 lyrics extension** (Schulze-Forster, Doire, Richard and Badeau), https://zenodo.org/record/3989267, licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (https://creativecommons.org/licenses/by-nc-sa/4.0/).

Halo is free, non-commercial software. Do not use these weights for any commercial purpose. JamendoLyrics was used only to measure accuracy, never to train.
