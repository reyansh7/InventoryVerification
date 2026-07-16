# Inventory AI

Warehouse inventory verification with YOLO. Upload photos or videos of stock, get automatic box and pallet counts, and compare them against your ERP CSV to spot missing or surplus items.

---

## What this project does

1. You enter a SKU / object code.
2. You upload warehouse photos or videos.
3. The backend runs a trained YOLO model and returns annotated media plus counts.
4. Counts are stored per SKU in a local SQLite database.
5. You upload an ERP CSV with expected quantities.
6. The UI shows **OK**, **Missing**, or **Surplus** per SKU.

Default model classes: **`box`** and **`pallet`**.

---

## Project structure

```
InventoryVerification4/
├── backend/                 # FastAPI API + SQLite DB + uploads
│   ├── main.py
│   ├── requirements.txt
│   ├── inventory.db         # created at runtime
│   └── uploads/             # annotated images/videos
├── frontend/                # React + Vite UI
├── train/ valid/ test/      # YOLO dataset (images + labels)
├── runs/train_results_yolo11l/weights/best.pt   # fine-tuned weights
├── data.yaml                # dataset class names / paths
├── verify_and_train.py      # train / resume YOLO from CLI
└── erp_data_test.csv        # example ERP file
```

---

## Requirements

- Python 3.10+ (3.11/3.13 work)
- Node.js 18+
- NVIDIA GPU recommended for training (CPU inference works but is slower)
- Packages used by the backend: FastAPI, Ultralytics YOLO, OpenCV, Pillow, imageio-ffmpeg, etc.

---

## Quick start

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
# Also install ML deps if missing:
pip install ultralytics opencv-python-headless pillow python-dotenv numpy
python main.py
```

Backend runs at **http://localhost:8000**.

Confirm it is up:

```bash
curl http://localhost:8000/
```

You should see a small JSON status message.

### 2. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL (usually **http://localhost:5173**).

Keep the backend running while you use the app. If the UI says the backend is down, restart `python main.py` from the `backend/` folder.

---

## How to use the app

### Scan inventory

1. Enter an **Object Code / SKU** (example: `ITEM-001`).
2. Drop or select photos and/or MP4 videos.
3. Click **Analyze Pending**.
4. Review annotated results and counts (boxes / pallets).
5. Counts are saved under that SKU in **Warehouse Inventory**.

Tips:

- Click a SKU in the inventory panel to reload its past scans.
- Drag one SKU onto another to **merge** all scans into the target SKU.
- Low-quality images may ask for a manual count.
- Exact duplicate files are flagged so you can choose whether to count them again.

### Upload ERP data

1. Click **Upload ERP** and choose a CSV.
2. Recommended columns: `SKU` (or object/item/code) and `Expected Qty` (or qty/quantity/count).
3. Example (`erp_data_test.csv`):

```csv
SKU,Expected Qty
test-001,54
test-002,155
test-003,100
test-004,30
```

4. Each SKU under that ERP shows:
   - detected boxes / pallets
   - ERP expected qty
   - status: **OK** / **Missing N** / **Surplus N**

### Move a class between ERP files

- Drag a SKU card onto another uploaded ERP file to link it there.
- Expected qty comes from **that ERP’s uploaded catalog**.
- If the SKU was never in that ERP CSV, expected qty is **0**.

### Export / cleanup

- **Export CSV** — download a scan report (detected vs expected).
- **Clear DB** — wipe scan + ERP rows (use carefully).
- Trash icons remove a SKU, a single scan, an ERP item, or an entire ERP file.

---

## Model used by the app

The backend loads:

```text
runs/train_results_yolo11l/weights/best.pt
```

That checkpoint is trained for:

| Class ID | Name   |
|----------|--------|
| 0        | box    |
| 1        | pallet |

Configured in `data.yaml`:

```yaml
nc: 2
names: ['box', 'pallet']
```

If `best.pt` is missing, inference will fail or fall back incorrectly — keep that path intact after training.

---

## Retrain the current box + pallet model

Use this when you want better accuracy on the **same** two classes (more warehouse photos, harder lighting, etc.).

### Dataset layout (YOLO detection format)

```text
train/images/*.jpg
train/labels/*.txt
valid/images/*.jpg
valid/labels/*.txt
test/images/...   (optional)
```

Each label file is one line per object:

```text
class_id x_center y_center width height
```

All values except `class_id` are normalized `0–1` relative to image width/height.

Example label line for a box:

```text
0 0.512 0.440 0.210 0.330
```

### Train / resume

From the project root:

```bash
python verify_and_train.py
```

This script:

1. Checks that train/valid (and optional test) folders look valid.
2. Resumes from `runs/train_results_yolo11l/weights/last.pt` if present.
3. Otherwise starts from `yolo11l.pt` and writes to `runs/train_results_yolo11l/`.

When training finishes, restart the backend so it reloads `best.pt`.

---

## Train the model to detect more than boxes (and improve it)

The shipped model only knows **box** and **pallet**. To detect other warehouse objects (crates, drums, totes, bags, forklifts, people, etc.), you must **expand the class list, label new data, and retrain**.

### Step 1 — Decide your classes

Example: keep boxes/pallets and add drums + totes.

Update `data.yaml`:

```yaml
train: train/images
val: valid/images
test: test/images

nc: 4
names: ['box', 'pallet', 'drum', 'tote']
```

**Important:** class IDs are positional:

| ID | Name   |
|----|--------|
| 0  | box    |
| 1  | pallet |
| 2  | drum   |
| 3  | tote   |

Do not reorder names later without relabeling — ID `2` will always mean whatever is third in `names`.

### Step 2 — Collect images

Gather many real examples of each new object:

- Different warehouses / angles / distances
- Bright, dark, blurry, and partially occluded shots
- Stacked and single items
- At least dozens of images per new class (hundreds is better)

Put them into `train/images` and `valid/images` (keep a real validation split).

### Step 3 — Label bounding boxes

Use a tool such as:

- [Roboflow](https://roboflow.com/)
- [CVAT](https://www.cvat.ai/)
- [Label Studio](https://labelstud.io/)
- Ultralytics Hub / other YOLO labelers

Export as **YOLOv8 / Ultralytics detection** labels (one `.txt` per image).

For every object in an image, draw a tight box and assign the correct class ID from `data.yaml`.

Tips for better models:

- Label **every** visible instance of your target classes (don’t skip hard ones).
- Include negatives (warehouse scenes with no target objects) so the model learns when to predict nothing.
- Keep old box/pallet labels when adding classes — otherwise the model can forget them (catastrophic forgetting).
- Match train and valid distributions (same kinds of scenes in both).

### Step 4 — Retrain

Option A — use the project trainer (update paths / epochs in the script if needed):

```bash
python verify_and_train.py
```

Option B — train directly with Ultralytics:

```bash
yolo detect train data=data.yaml model=yolo11l.pt epochs=100 imgsz=1024 batch=2 workers=0 project=. name=runs/train_results_custom
```

Or in Python:

```python
from ultralytics import YOLO

model = YOLO("yolo11l.pt")  # or your previous best.pt to fine-tune
model.train(
    data="data.yaml",
    epochs=100,
    imgsz=1024,
    batch=2,
    workers=0,
    project=".",
    name="runs/train_results_custom",
)
```

### Step 5 — Point the app at the new weights

In `backend/main.py`, `MODEL_PATH` should point at your new `best.pt`, for example:

```python
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "runs", "train_results_custom", "weights", "best.pt"
)
```

Restart the backend.

### Step 6 — Teach the app about new class counts (optional but recommended)

Today the UI/API mainly tally **`box`** and **`pallet`**. After you add classes like `drum` / `tote`, update the counting logic in `backend/main.py` (`analyze_batch` / `analyze_video`) and the frontend labels so new classes are stored and shown the same way boxes/pallets are.

Until you do that, the model may detect new objects in annotated frames, but the inventory counters may still only increment for box/pallet.

### Improving accuracy over time

| Goal | What to do |
|------|------------|
| Misses objects | Add more labeled examples of those misses; retrain |
| False positives | Add hard negatives; lower confidence carefully after retraining |
| Only works in one warehouse | Add images from other sites/lighting |
| New product type | Add a class in `data.yaml`, label it, retrain, update app counters |
| Keep old performance | Always mix old box/pallet data into the new training set |

Workflow that works well in practice:

1. Run scans in the app and note failures.
2. Export or save those images.
3. Label the missing/wrong objects.
4. Merge into `train/` + `valid/`.
5. Retrain and swap `best.pt`.
6. Restart backend and re-test the same scenes.

---

## ERP CSV notes

The uploader looks at header names (case-insensitive):

- SKU field: headers containing `sku`, `object`, `item`, or `code`
- Qty field: headers containing `qty`, `quant`, `expected`, or `count`

If your export uses different headers, rename them before upload or adjust the parser in `backend/main.py` (`/erp/upload`).

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ERR_CONNECTION_REFUSED` on port 8000 | Start backend from `backend/`: `python main.py` |
| Model counts always 0 | Confirm `MODEL_PATH` points to fine-tuned `best.pt` (box/pallet), not a generic COCO `yolo11l.pt` |
| Video player is black | Result videos are re-encoded to H.264; restart backend on latest code and re-analyze if needed |
| ERP expected qty wrong after drag | Qty comes from the **target** ERP catalog; re-upload that ERP CSV if the catalog was wiped |
| Training OOM on Windows | Keep `workers=0`, lower `batch`, or use a smaller base model (`yolo11m.pt` / `yolo11n.pt`) |

---

## Tech stack

- **Frontend:** React, TypeScript, Vite
- **Backend:** FastAPI, SQLite, OpenCV
- **ML:** Ultralytics YOLO (`yolo11l` fine-tuned), optional Gemini-assisted tooling in backend for experimental auto-label flows

---

## License / data

Dataset metadata in `data.yaml` references a Roboflow project for box/pallet detection. Respect that dataset’s license if you redistribute weights or images.
