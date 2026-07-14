import os
import cv2
from glob import glob

BASE_DIR = os.path.dirname(__file__)
IMG_DIR = os.path.join(BASE_DIR, "autotrain_dataset", "images", "train")
LBL_DIR = os.path.join(BASE_DIR, "autotrain_dataset", "labels", "train")
OUT_DIR = os.path.join(BASE_DIR, "autotrain_dataset", "annotated_previews")

os.makedirs(OUT_DIR, exist_ok=True)

images = glob(os.path.join(IMG_DIR, "*.jpg"))
classes = {0: ("box", (0, 255, 0)), 1: ("pallet", (255, 0, 0))}

for img_path in images:
    filename = os.path.basename(img_path)
    lbl_path = os.path.join(LBL_DIR, filename.replace(".jpg", ".txt"))
    
    if not os.path.exists(lbl_path):
        continue
        
    img = cv2.imread(img_path)
    if img is None:
        continue
        
    h, w = img.shape[:2]
    
    with open(lbl_path, "r") as f:
        lines = f.readlines()
        
    for line in lines:
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        cls_id = int(parts[0])
        x_c, y_c, bw, bh = map(float, parts[1:])
        
        # Convert YOLO normalized coordinates to pixel coordinates
        x1 = int((x_c - bw/2) * w)
        y1 = int((y_c - bh/2) * h)
        x2 = int((x_c + bw/2) * w)
        y2 = int((y_c + bh/2) * h)
        
        name, color = classes.get(cls_id, ("unknown", (0, 0, 255)))
        
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, name, (x1, max(y1-5, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        
    out_path = os.path.join(OUT_DIR, filename)
    cv2.imwrite(out_path, img)

print(f"Annotated images saved to {OUT_DIR}")
