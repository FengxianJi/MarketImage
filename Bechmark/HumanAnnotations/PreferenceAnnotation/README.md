# EmergingArt Preference Annotation

Local browser GUI for ranking every 6-image group in `./EmergingArt`.

## Run

```bash
cd PreferenceAnnotation
python app.py --port 8765
```

Open the printed URL, usually:

```text
http://127.0.0.1:8765
```

## Output

Annotations are saved incrementally to:

```text
annotations/emergingart_annotations.json
```

Each saved record contains:

- annotator name
- dataset split
- group id
- original group order and image source order from the dataset JSON
- ranked folder ids, where rank 1 is the most preferred image
- ranked items with original prices for later evaluation
- source group items
- notes and duration

The GUI does not display original prices or artwork metadata during annotation.

## Notes

- Images are initially shown in the same order as the corresponding `data/*.json` file.
- Previously saved groups reopen in the saved ranking order so an annotator can revise them.
- The Limit field scopes annotation to the first N groups in dataset order.
- On startup, annotator switch, dataset switch, or Limit change, the GUI jumps to the first unfinished group in the current scope.
- The annotation API returns only visual assets and workflow identifiers, not `description.txt` content.
