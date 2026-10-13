# My illustrations

Put your bird images here, named for the species' scientific name as
BirdNET-Pi stores it: `Cardinalis cardinalis.jpg`. Then run
`scripts/fetch_plates.py` and restart the service. To see which species
still need an image, run `scripts/missing_plates.py`.

An image with any other name needs a line in `../folios/mine.yaml`, which
is also where you add a legend or other fields.

- One bird per image works best. For several birds, set `composite: true`.
- Portrait, about 3:4, at least 2,000 px on the long side.
- JPEG or PNG, gray or color.
- A light background is evened out to white. Anything darker is kept as part of the picture.

Images in this folder are committed to the repository like any other file.
If you'd rather keep them out of git, add `server/local/images/*` to `.gitignore`.
