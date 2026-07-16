import io
import os
import base64
import tempfile
import cv2
import sqlite3
import csv
import codecs
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ultralytics import YOLO
from PIL import Image
import numpy as np
import uuid
import shutil
import random
import time
import json
from glob import glob
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

try:
    from google import genai
    from google.genai import types
except ImportError:
    pass

app = FastAPI(title="YOLO Inventory Verification")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Box-Count", "X-Pallet-Count", "X-Is-Duplicate"],
)

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inventory.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_code TEXT,
            filename TEXT,
            file_size INTEGER,
            box_count INTEGER,
            pallet_count INTEGER,
            file_path TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Check if csv_files exists. If not, this is the migration point.
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='csv_files'")
    if not c.fetchone():
        c.execute('''
            CREATE TABLE csv_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Insert a dummy record for existing data
        c.execute("INSERT INTO csv_files (filename) VALUES ('Legacy_ERP.csv')")
        legacy_id = c.lastrowid
        
        # Check if old erp_data exists
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='erp_data'")
        if c.fetchone():
            c.execute('ALTER TABLE erp_data RENAME TO erp_data_old')
            c.execute('''
                CREATE TABLE erp_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    csv_id INTEGER,
                    object_code TEXT,
                    expected_qty INTEGER
                )
            ''')
            c.execute(f'INSERT INTO erp_data (csv_id, object_code, expected_qty) SELECT {legacy_id}, object_code, expected_qty FROM erp_data_old')
            c.execute('DROP TABLE erp_data_old')
        else:
            c.execute('''
                CREATE TABLE erp_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    csv_id INTEGER,
                    object_code TEXT,
                    expected_qty INTEGER
                )
            ''')
    else:
        # Table exists, ensure erp_data does too just in case
        c.execute('''
            CREATE TABLE IF NOT EXISTS erp_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                csv_id INTEGER,
                object_code TEXT,
                expected_qty INTEGER
            )
        ''')

    # Permanent per-ERP expected qtys from upload. Survives drag/move between ERPs.
    c.execute('''
        CREATE TABLE IF NOT EXISTS erp_catalog (
            csv_id INTEGER NOT NULL,
            object_code TEXT NOT NULL,
            expected_qty INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (csv_id, object_code)
        )
    ''')
    # Seed catalog from current erp_data for existing DBs
    c.execute('''
        INSERT OR IGNORE INTO erp_catalog (csv_id, object_code, expected_qty)
        SELECT csv_id, object_code, expected_qty FROM erp_data
    ''')
    # If an active erp_data row has a real qty and catalog is 0, prefer the real qty
    c.execute('''
        UPDATE erp_catalog
        SET expected_qty = (
            SELECT e.expected_qty FROM erp_data e
            WHERE e.csv_id = erp_catalog.csv_id AND e.object_code = erp_catalog.object_code
        )
        WHERE expected_qty = 0
          AND EXISTS (
            SELECT 1 FROM erp_data e
            WHERE e.csv_id = erp_catalog.csv_id
              AND e.object_code = erp_catalog.object_code
              AND e.expected_qty > 0
          )
    ''')

    # Refresh catalog (+ active rows) from original CSV files still on disk
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for csv_row in c.execute('SELECT id, filename FROM csv_files').fetchall():
        csv_id, filename = csv_row
        if not filename:
            continue
        path = os.path.join(base_dir, filename)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sku = None
                    qty = 0
                    for k, v in row.items():
                        if not k or v is None:
                            continue
                        kl = k.lower().strip()
                        if 'sku' in kl or 'object' in kl or 'item' in kl or 'code' in kl:
                            if not sku:
                                sku = str(v).strip()
                        if 'qty' in kl or 'quant' in kl or 'expected' in kl:
                            try:
                                qty = int(str(v).strip())
                            except Exception:
                                pass
                    if not sku:
                        continue
                    c.execute(
                        '''INSERT INTO erp_catalog (csv_id, object_code, expected_qty)
                           VALUES (?, ?, ?)
                           ON CONFLICT(csv_id, object_code) DO UPDATE SET expected_qty=excluded.expected_qty''',
                        (csv_id, sku, qty),
                    )
                    c.execute(
                        'UPDATE erp_data SET expected_qty = ? WHERE csv_id = ? AND object_code = ?',
                        (qty, csv_id, sku),
                    )
        except Exception as e:
            print(f"Catalog repair skipped for {filename}: {e}")

    # Add file_path if it doesn't exist (for existing DB)
    try:
        c.execute('ALTER TABLE scans ADD COLUMN file_path TEXT')
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()

init_db()

def check_is_duplicate(filename: str, file_size: int) -> list:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT DISTINCT object_code FROM scans WHERE filename=? AND file_size=?', (filename, file_size))
    results = c.fetchall()
    conn.close()
    return [r[0] for r in results]

def insert_scan(object_code: str, filename: str, file_size: int, box_count: int, pallet_count: int, file_path: str = None) -> int:
    if not object_code:
        return None
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO scans (object_code, filename, file_size, box_count, pallet_count, file_path)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (object_code, filename, file_size, box_count, pallet_count, file_path))
    conn.commit()
    scan_id = c.lastrowid
    conn.close()
    return scan_id

@app.get("/inventory")
def get_inventory():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT s.object_code, SUM(s.box_count) as total_boxes, SUM(s.pallet_count) as total_pallets, COUNT(s.id) as scan_count, e.expected_qty
        FROM scans s
        LEFT JOIN erp_data e ON s.object_code = e.object_code
        GROUP BY s.object_code
        UNION
        SELECT e.object_code, 0 as total_boxes, 0 as total_pallets, 0 as scan_count, e.expected_qty
        FROM erp_data e
        WHERE e.object_code NOT IN (SELECT object_code FROM scans WHERE object_code IS NOT NULL)
        ORDER BY object_code ASC
    ''')
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

from pydantic import BaseModel
class ScanAddRequest(BaseModel):
    object_code: str
    filename: str
    file_size: int
    box_count: int
    pallet_count: int
    file_path: Optional[str] = None

class AutoTrainRequest(BaseModel):
    scan_ids: List[int]
    api_keys: Optional[List[str]] = None

@app.post("/inventory/add")
def force_add_inventory(req: ScanAddRequest):
    scan_id = insert_scan(req.object_code, req.filename, req.file_size, req.box_count, req.pallet_count, req.file_path)
    return {"status": "success", "scan_id": scan_id}

@app.delete("/inventory/clear")
def clear_inventory():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM scans')
    c.execute('DELETE FROM erp_data')
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.get("/inventory/{object_code}/scans")
def get_object_scans(object_code: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT id, object_code, filename, file_size, box_count, pallet_count, file_path, timestamp
        FROM scans
        WHERE object_code = ?
        ORDER BY timestamp DESC
    ''', (object_code,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.delete("/inventory/scan/{scan_id}")
def delete_scan(scan_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT file_path FROM scans WHERE id = ?', (scan_id,))
    row = c.fetchone()
    if row and row[0]:
        file_path = row[0]
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Failed to delete file {file_path}: {e}")
    
    c.execute('DELETE FROM scans WHERE id = ?', (scan_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.delete("/inventory/class/{object_code}")
def delete_class(object_code: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('SELECT file_path FROM scans WHERE object_code = ?', (object_code,))
    rows = c.fetchall()
    for row in rows:
        if row and row[0]:
            file_path = row[0]
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Failed to delete file {file_path}: {e}")
                    
    c.execute('DELETE FROM scans WHERE object_code = ?', (object_code,))
    c.execute('DELETE FROM erp_data WHERE object_code = ?', (object_code,))
    
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/erp/upload")
async def upload_erp(file: UploadFile = File(...)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    filename = file.filename or "uploaded.csv"
    c.execute('INSERT INTO csv_files (filename) VALUES (?)', (filename,))
    csv_id = c.lastrowid
    
    contents = await file.read()
    reader = csv.DictReader(codecs.iterdecode(io.BytesIO(contents), 'utf-8'))
    
    for row in reader:
        sku = None
        qty = 0
        for k, v in row.items():
            if not k: continue
            kl = k.lower().strip()
            if 'sku' in kl or 'object' in kl or 'item' in kl or 'code' in kl:
                if not sku: sku = v.strip()
            if 'qty' in kl or 'quant' in kl or 'expected' in kl or 'count' in kl:
                try:
                    qty = int(v.strip())
                except:
                    pass
        if sku:
            c.execute(
                'INSERT INTO erp_data (csv_id, object_code, expected_qty) VALUES (?, ?, ?)',
                (csv_id, sku, qty),
            )
            c.execute(
                '''INSERT INTO erp_catalog (csv_id, object_code, expected_qty)
                   VALUES (?, ?, ?)
                   ON CONFLICT(csv_id, object_code) DO UPDATE SET expected_qty=excluded.expected_qty''',
                (csv_id, sku, qty),
            )
    
    conn.commit()
    conn.close()
    return {"status": "success", "csv_id": csv_id}

@app.get("/erp/files")
def get_erp_files():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM csv_files ORDER BY uploaded_at DESC')
    files = [dict(row) for row in c.fetchall()]
    
    for file in files:
        c.execute(
            '''SELECT e.object_code,
                      COALESCE(cat.expected_qty, e.expected_qty) AS expected_qty
               FROM erp_data e
               LEFT JOIN erp_catalog cat
                 ON cat.csv_id = e.csv_id AND cat.object_code = e.object_code
               WHERE e.csv_id = ?''',
            (file['id'],),
        )
        file['items'] = [dict(row) for row in c.fetchall()]
        
    conn.close()
    return files

class AddErpItemRequest(BaseModel):
    object_code: str
    expected_qty: int = 0

@app.post("/erp/files/{csv_id}/items")
def add_erp_item(csv_id: int, req: AddErpItemRequest):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Expected qty always comes from THIS ERP's catalog (uploaded CSV).
    # If the class was never in this ERP, qty is 0 — never borrow from another ERP.
    c.execute(
        'SELECT expected_qty FROM erp_catalog WHERE csv_id = ? AND object_code = ?',
        (csv_id, req.object_code),
    )
    catalog_row = c.fetchone()
    expected_qty = catalog_row[0] if catalog_row is not None else 0

    c.execute('DELETE FROM erp_data WHERE object_code = ?', (req.object_code,))
    c.execute(
        'INSERT INTO erp_data (csv_id, object_code, expected_qty) VALUES (?, ?, ?)',
        (csv_id, req.object_code, expected_qty),
    )
    conn.commit()
    conn.close()
    return {"status": "success", "expected_qty": expected_qty}

@app.delete("/erp/files/{csv_id}/items/{object_code}")
def delete_erp_item(csv_id: int, object_code: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM erp_data WHERE csv_id = ? AND object_code = ?', (csv_id, object_code))
    c.execute('DELETE FROM erp_catalog WHERE csv_id = ? AND object_code = ?', (csv_id, object_code))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.delete("/erp/files/{csv_id}")
def delete_erp_file(csv_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM erp_data WHERE csv_id = ?', (csv_id,))
    c.execute('DELETE FROM erp_catalog WHERE csv_id = ?', (csv_id,))
    c.execute('DELETE FROM csv_files WHERE id = ?', (csv_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}

class MergeRequest(BaseModel):
    source_object_code: str
    target_object_code: str

@app.patch("/inventory/merge")
def merge_inventory_class(req: MergeRequest):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('UPDATE scans SET object_code = ? WHERE object_code = ?', 
              (req.target_object_code, req.source_object_code))
    conn.commit()
    conn.close()
    return {"status": "success"}

# Load the fine-tuned inventory model (box + pallet classes)
MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "runs", "train_results_yolo11l", "weights", "best.pt"
)

try:
    model = YOLO(MODEL_PATH)
    print(f"Loaded model successfully from {MODEL_PATH}")
except Exception as e:
    print(f"Failed to load model from {MODEL_PATH}: {e}")
    model = None

def _rmtree_robust(path: str):
    """Windows-safe recursive directory removal that handles read-only/locked files."""
    import stat
    def _onerror(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception as e:
            print(f"  Warning: could not remove {path}: {e}")
    if os.path.exists(path):
        shutil.rmtree(path, onerror=_onerror)

def _get_mime_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    return {"png": "image/png", ".png": "image/png", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(ext, "image/jpeg")

# Global training status tracker
TRAINING_STATUS = {
    "running": False,
    "phase": "",           # "labeling", "training", "validating", "done", "error"
    "total": 0,
    "labeled": 0,
    "failed": 0,
    "message": ""
}

def _call_gemini_with_retry(clients: list, model_name: str, contents, config, max_retries_per_key: int = 4):
    """Call Gemini with key rotation on rate limit errors, and exponential backoff if all keys fail."""
    delay = 5  # start with 5 seconds
    for attempt in range(max_retries_per_key):
        for idx, client in enumerate(clients):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                return response
            except Exception as e:
                err_str = str(e)
                is_rate_limit = ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str or
                                 "quota" in err_str.lower() or
                                 "503" in err_str or "UNAVAILABLE" in err_str or
                                 "high demand" in err_str.lower() or "overloaded" in err_str.lower())
                
                if is_rate_limit:
                    if len(clients) > 1 and idx < len(clients) - 1:
                        print(f"  -> Key {idx+1} rate limited. Switching to key {idx+2}...")
                        TRAINING_STATUS["message"] = f"Key {idx+1} rate limited, switching to key {idx+2}..."
                        continue  # Try next key immediately
                    else:
                        is_last_attempt = attempt == max_retries_per_key - 1
                        if not is_last_attempt:
                            wait = delay * (2 ** attempt)  # exponential: 5, 10, 20, 40s
                            print(f"  -> All keys rate limited. Waiting {wait}s before retry round {attempt+2}/{max_retries_per_key}...")
                            TRAINING_STATUS["message"] = f"All keys rate limited, waiting {wait}s..."
                            time.sleep(wait)
                            break  # Break inner loop, go to next attempt round (which starts back at key 0)
                        else:
                            raise
                else:
                    raise  # Not a rate limit error

def background_training_task(scan_ids: List[int], api_keys: List[str] = None):
    global model, TRAINING_STATUS
    
    TRAINING_STATUS.update({
        "running": True, "phase": "starting",
        "total": len(scan_ids), "labeled": 0, "failed": 0,
        "message": f"Starting autotrain for {len(scan_ids)} scan(s)..."
    })
    
    if not api_keys:
        env_key = os.environ.get("GEMINI_API_KEY")
        api_keys = [env_key] if env_key and env_key != "your_api_key_here" else []
        
    if not api_keys:
        TRAINING_STATUS.update({"running": False, "phase": "error", "message": "No GEMINI_API_KEY provided."})
        return
        
    clients = [genai.Client(api_key=key) for key in api_keys]
    
    base_dir = os.path.dirname(os.path.dirname(__file__))
    autotrain_dir = os.path.join(base_dir, "autotrain_dataset")
    img_train_dir = os.path.join(autotrain_dir, "images", "train")
    lbl_train_dir = os.path.join(autotrain_dir, "labels", "train")
    
    # Robustly clean up any previous autotrain run
    _rmtree_robust(autotrain_dir)
    os.makedirs(img_train_dir, exist_ok=True)
    os.makedirs(lbl_train_dir, exist_ok=True)

    TRAINING_STATUS["phase"] = "labeling"
    label_map = {"box": 0, "pallet": 1}
    processed_count = 0

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    for scan_id in scan_ids:
        c.execute('SELECT file_path, object_code FROM scans WHERE id = ?', (scan_id,))
        row = c.fetchone()
        
        if not row or not row[0]:
            print(f"Scan {scan_id} or file not found. Skipping.")
            continue
            
        file_path = row[0]
        if not os.path.exists(file_path):
            print(f"File {file_path} does not exist on disk. Skipping scan {scan_id}.")
            continue
        
        TRAINING_STATUS["message"] = f"Labeling scan {processed_count + TRAINING_STATUS['failed'] + 1}/{len(scan_ids)}: scan {scan_id}"
        print(f"Processing scan {scan_id}: {file_path}")
        try:
            with open(file_path, "rb") as f:
                image_bytes = f.read()
            
            mime_type = _get_mime_type(file_path)
            
            # Throttle to ~10 RPM to stay safely under free-tier limit of 15 RPM
            if processed_count + TRAINING_STATUS["failed"] > 0:
                time.sleep(6)
                
            prompt = (
                "You are a warehouse inventory AI. Carefully detect ALL inventory items "
                "(including cardboard boxes, wooden pallets, stacked white bales, and bundles of paper) "
                "visible in this image, including partially visible ones.\n"
                "Return ONLY a JSON object with this exact structure:\n"
                '{"detections": [{"label": "box", "xmin": 120, "ymin": 80, "xmax": 450, "ymax": 390}]}\n'
                "Rules:\n"
                "- label must be exactly 'box' or 'pallet' (lowercase). Treat ANY stackable inventory items (bales, paper bundles, crates, etc.) as 'box'.\n"
                "- coordinates are integers 0-1000, where (0,0) is top-left and (1000,1000) is bottom-right\n"
                "- xmax must be greater than xmin, ymax must be greater than ymin\n"
                "- Return empty detections array if nothing is found\n"
                "- No markdown, no explanation, only the raw JSON"
            )
            
            response = _call_gemini_with_retry(
                clients, 'gemini-3.5-flash',
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type), 
                    prompt
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=types.Schema(
                        type=types.Type.OBJECT,
                        required=["detections"],
                        properties={
                            "detections": types.Schema(
                                type=types.Type.ARRAY,
                                items=types.Schema(
                                    type=types.Type.OBJECT,
                                    required=["label", "xmin", "ymin", "xmax", "ymax"],
                                    properties={
                                        "label": types.Schema(type=types.Type.STRING),
                                        "xmin": types.Schema(type=types.Type.INTEGER),
                                        "ymin": types.Schema(type=types.Type.INTEGER),
                                        "xmax": types.Schema(type=types.Type.INTEGER),
                                        "ymax": types.Schema(type=types.Type.INTEGER)
                                    }
                                )
                            )
                        }
                    )
                )
            )
            
            clean_text = response.text.strip()
            # Strip any accidental markdown wrappers
            for prefix in ("```json", "```"):
                if clean_text.startswith(prefix):
                    clean_text = clean_text[len(prefix):]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()
            
            data = json.loads(clean_text)
        except Exception as e:
            print(f"Gemini API failed for scan {scan_id}: {e}")
            TRAINING_STATUS["failed"] += 1
            continue
            
        detections = data.get("detections", [])
        print(f"  -> Gemini returned {len(detections)} detection(s) for scan {scan_id}.")
        
        if not detections:
            print(f"  -> No detections returned for scan {scan_id}. Skipping (won't write empty label).")
            TRAINING_STATUS["failed"] += 1
            continue
        
        # Copy image to training folder
        ext = os.path.splitext(file_path)[1] or ".jpg"
        target_img_name = f"target_{scan_id}{ext}"
        shutil.copy(file_path, os.path.join(img_train_dir, target_img_name))
        
        label_file_name = f"target_{scan_id}.txt"
        with open(os.path.join(lbl_train_dir, label_file_name), "w") as f:
            for det in detections:
                lbl = det.get("label", "").lower().strip()
                if lbl not in label_map:
                    continue
                try:
                    xmin = float(det.get("xmin", 0))
                    ymin = float(det.get("ymin", 0))
                    xmax = float(det.get("xmax", 0))
                    ymax = float(det.get("ymax", 0))
                    
                    # Clamp to valid range
                    xmin = max(0.0, min(1000.0, xmin))
                    ymin = max(0.0, min(1000.0, ymin))
                    xmax = max(0.0, min(1000.0, xmax))
                    ymax = max(0.0, min(1000.0, ymax))
                    
                    if xmax <= xmin or ymax <= ymin:
                        print(f"  -> Skipping invalid bbox: {det}")
                        continue
                    
                    cls_id = label_map[lbl]
                    x_c = ((xmin + xmax) / 2) / 1000.0
                    y_c = ((ymin + ymax) / 2) / 1000.0
                    w = (xmax - xmin) / 1000.0
                    h = (ymax - ymin) / 1000.0
                    f.write(f"{cls_id} {x_c:.6f} {y_c:.6f} {w:.6f} {h:.6f}\n")
                except Exception as e:
                    print(f"  -> Skipping malformed detection {det}: {e}")
        processed_count += 1
        TRAINING_STATUS["labeled"] = processed_count
        TRAINING_STATUS["message"] = f"Labeled {processed_count}/{len(scan_ids)} scans."
        
    conn.close()
    
    if processed_count == 0:
        print("No scans were successfully processed by Gemini. Aborting training.")
        TRAINING_STATUS.update({"running": False, "phase": "error",
                                 "message": "Gemini could not label any scans. Aborting."})
        _rmtree_robust(autotrain_dir)
        return
    
    TRAINING_STATUS["phase"] = "training"
    TRAINING_STATUS["message"] = f"Gemini labeled {processed_count} scans. Starting YOLO fine-tuning..."
    print(f"Gemini labeled {processed_count}/{len(scan_ids)} scan(s). Applying Replay Buffer...")
    orig_img_dir = os.path.join(base_dir, "train", "images")
    orig_lbl_dir = os.path.join(base_dir, "train", "labels")
    
    if os.path.exists(orig_img_dir) and os.path.exists(orig_lbl_dir):
        all_imgs = glob(os.path.join(orig_img_dir, "*.jpg")) + glob(os.path.join(orig_img_dir, "*.png"))
        if all_imgs:
            valid_samples = []
            for src_img in all_imgs:
                img_name = os.path.basename(src_img)
                src_lbl = os.path.join(orig_lbl_dir, os.path.splitext(img_name)[0] + ".txt")
                if not os.path.exists(src_lbl):
                    continue
                # Only use detection-format labels (5 columns), skip segmentation labels
                try:
                    with open(src_lbl, "r") as lf:
                        first_line = lf.readline().strip()
                    if first_line and len(first_line.split()) == 5:
                        valid_samples.append(src_img)
                except Exception:
                    pass
            
            samples = random.sample(valid_samples, min(20, len(valid_samples)))
            for src_img in samples:
                img_name = os.path.basename(src_img)
                src_lbl = os.path.join(orig_lbl_dir, os.path.splitext(img_name)[0] + ".txt")
                shutil.copy(src_img, os.path.join(img_train_dir, img_name))
                shutil.copy(src_lbl, os.path.join(lbl_train_dir, os.path.splitext(img_name)[0] + ".txt"))
            print(f"  -> Added {len(samples)} detect-only replay buffer samples.")
    
    yaml_path = os.path.join(autotrain_dir, "autotrain.yaml")
    # Use forward slashes in YAML (YOLO requires this even on Windows)
    autotrain_dir_fwd = autotrain_dir.replace("\\", "/")
    with open(yaml_path, "w") as f:
        f.write(f"path: {autotrain_dir_fwd}\n")
        f.write("train: images/train\n")
        f.write("val: images/train\n")
        f.write("nc: 2\n")
        f.write("names: ['box', 'pallet']\n")
    
    # --- Safe model backup before training ---
    if not os.path.exists(MODEL_PATH):
        print(f"Error: Base model not found at {MODEL_PATH}. Aborting.")
        _rmtree_robust(autotrain_dir)
        return
    
    backup_path = MODEL_PATH.replace(".pt", f"_backup_{int(time.time())}.pt")
    shutil.copy(MODEL_PATH, backup_path)
    print(f"Model safely backed up to {backup_path}")
    
    print("Starting YOLO fine-tuning (10 epochs, freeze backbone)...")
    new_best_path = None
    try:
        # Free the global inference model from GPU memory before training
        # to avoid CUDA out-of-memory / Windows paging file exhaustion
        global model
        model = None
        import gc, torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("  -> Freed inference model from GPU memory.")
        
        train_model = YOLO(MODEL_PATH)
        results = train_model.train(
            data=yaml_path,
            epochs=10,
            imgsz=1024,
            max_det=1000,
            batch=4,        # Small batch to stay within GPU VRAM
            workers=0,      # workers=0 required on Windows to avoid paging file OOM
            freeze=10,      # Freeze first 10 layers to protect backbone features
            lr0=0.001,      # Lower LR to avoid catastrophic forgetting
            lrf=0.01,
            patience=5,     # Stop early if no improvement
            plots=False,    # Skip plots during background training
            verbose=False
        )
        del train_model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        new_best_path = os.path.join(results.save_dir, "weights", "best.pt")
        
        if not os.path.exists(new_best_path):
            raise FileNotFoundError("Training did not produce best.pt weights.")
        
        # --- Validate new model before swapping ---
        print("Validating new model before swap...")
        new_model_val = YOLO(new_best_path)
        new_metrics = new_model_val.val(data=yaml_path, verbose=False, workers=0)
        new_map = new_metrics.box.map  # mAP@0.5:0.95
        
        old_model_val = YOLO(backup_path)
        old_metrics = old_model_val.val(data=yaml_path, verbose=False, workers=0)
        old_map = old_metrics.box.map
        
        print(f"  Old model mAP: {old_map:.4f} | New model mAP: {new_map:.4f}")
        
        if new_map >= old_map * 0.95:  # Accept if not more than 5% worse
            shutil.copy(new_best_path, MODEL_PATH)
            model = YOLO(MODEL_PATH)
            msg = f"✅ Done! Model improved (mAP: {old_map:.4f} -> {new_map:.4f})."
            print(msg)
            TRAINING_STATUS.update({"running": False, "phase": "done", "message": msg})
        else:
            model = YOLO(MODEL_PATH)  # Reload original
            msg = f"⚠️ New model was worse (mAP: {old_map:.4f} -> {new_map:.4f}). Original kept."
            print(msg)
            TRAINING_STATUS.update({"running": False, "phase": "done", "message": msg})
            
    except Exception as e:
        msg = f"YOLO training failed: {e}"
        print(msg)
        TRAINING_STATUS.update({"running": False, "phase": "error", "message": msg})
        print("Restoring backup model...")
        try:
            shutil.copy(backup_path, MODEL_PATH)
        except Exception as restore_err:
            print(f"❌ Failed to copy backup: {restore_err}")
        try:
            model = YOLO(MODEL_PATH)
            print("✅ Original model restored and reloaded successfully.")
        except Exception as reload_err:
            print(f"❌ Failed to reload model: {reload_err}")
    finally:
        # Clean up temporary dataset to avoid future permission errors
        time.sleep(2)  # Brief wait for YOLO to release file handles
        _rmtree_robust(autotrain_dir)
        print("Cleaned up temporary training dataset.")

@app.post("/autotrain")
def trigger_autotrain(req: AutoTrainRequest, background_tasks: BackgroundTasks):
    if TRAINING_STATUS["running"]:
        return {"status": "busy", "message": "A training job is already running.", "training_status": TRAINING_STATUS}
    background_tasks.add_task(background_training_task, req.scan_ids, req.api_keys)
    return {"status": "success", "message": f"Autotraining initiated for {len(req.scan_ids)} scan(s)."}

@app.get("/autotrain/status")
def get_autotrain_status():
    return TRAINING_STATUS

@app.get("/")
def read_root():
    return {"status": "ok", "message": "YOLO Backend is running."}

from typing import Tuple

def check_image_quality(image: np.ndarray, is_video: bool = False) -> Tuple[bool, str]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    mean_brightness = np.mean(gray)
    
    blur_threshold = 30.0 if is_video else 50.0
    
    if laplacian_var < blur_threshold:
        return False, "Image is too blurry."
    if mean_brightness < 40:
        return False, "Image is too dark."
    if mean_brightness > 220:
        return False, "Image is overexposed (too bright)."
        
    return True, ""

@app.post("/analyze_batch")
async def analyze_batch(
    files: List[UploadFile] = File(...),
    object_code: Optional[str] = Form(None)
):
    if not model:
        return {"error": "Model not loaded properly."}
    
    response_data = []
    
    for file in files:
        contents = await file.read()
        file_size = len(contents)
        image = Image.open(io.BytesIO(contents)).convert("RGB")
        img_cv2 = np.array(image)[:, :, ::-1]
        
        is_good_quality, quality_reason = check_image_quality(img_cv2, is_video=False)
        if not is_good_quality:
            response_data.append({
                "is_low_quality": True,
                "quality_reason": quality_reason,
                "filename": file.filename,
                "file_size": file_size,
                "annotated_image": f"data:{file.content_type};base64,{base64.b64encode(contents).decode('utf-8')}"
            })
            continue
            
        duplicate_classes = check_is_duplicate(file.filename, file_size)
        is_dup = len(duplicate_classes) > 0
        
        results = model([image], augment=True, conf=0.20, iou=0.25, imgsz=1024, max_det=1000)
        result = results[0]
        
        box_count = 0
        pallet_count = 0
        
        for cls_idx in result.boxes.cls:
            class_id = int(cls_idx.item())
            class_name = result.names[class_id]
            if class_name == "box":
                box_count += 1
            elif class_name == "pallet":
                pallet_count += 1
                
        annotated_img_array = result.plot()
        annotated_img_pil = Image.fromarray(annotated_img_array[..., ::-1])
        
        file_name = f"{uuid.uuid4().hex}.jpg"
        file_path = f"uploads/{file_name}"
        annotated_img_pil.save(os.path.join(UPLOADS_DIR, file_name), format="JPEG")
        url = f"http://localhost:8000/{file_path}"
        
        scan_id = None
        if not is_dup:
            scan_id = insert_scan(object_code, file.filename, file_size, box_count, pallet_count, file_path)
            
        response_data.append({
            "scan_id": scan_id,
            "box_count": box_count,
            "pallet_count": pallet_count,
            "annotated_image": url,
            "file_path": file_path,
            "is_duplicate": is_dup,
            "duplicate_classes": duplicate_classes,
            "filename": file.filename,
            "file_size": file_size
        })
        
    return response_data


def remove_file(path: str):
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except Exception as e:
        print(f"Error removing temp file {path}: {e}")

def create_video_writer(output_path: str, fps: float, width: int, height: int):
    """OpenCV codec support varies on Windows; try common fallbacks."""
    if not fps or fps <= 0 or fps != fps:
        fps = 25.0

    # H.264 / yuv420p requires even frame dimensions
    width = max(2, int(width) - (int(width) % 2))
    height = max(2, int(height) - (int(height) % 2))

    base, _ = os.path.splitext(output_path)
    candidates = [
        (output_path, "mp4v"),
        (output_path, "avc1"),
        (f"{base}.avi", "XVID"),
        (f"{base}.avi", "MJPG"),
    ]
    for path, fourcc_str in candidates:
        fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
        writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
        if writer.isOpened():
            return writer, path, width, height
        writer.release()
    return None, None, width, height

def transcode_video_for_browser(src_path: str) -> str:
    """Re-encode to H.264 MP4 so Chrome/Edge/Firefox can play the result."""
    try:
        import subprocess
        import imageio_ffmpeg
    except ImportError as e:
        print(f"Browser video transcode unavailable ({e}). Install imageio-ffmpeg.")
        return src_path

    base, _ = os.path.splitext(src_path)
    dst_path = f"{base}_browser.mp4"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y", "-i", src_path,
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "-an",
        dst_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(dst_path) or os.path.getsize(dst_path) == 0:
        print(f"ffmpeg transcode failed: {(result.stderr or '')[-800:]}")
        remove_file(dst_path)
        return src_path

    remove_file(src_path)
    final_path = f"{base}.mp4"
    if os.path.abspath(dst_path) != os.path.abspath(final_path):
        if os.path.exists(final_path):
            remove_file(final_path)
        os.replace(dst_path, final_path)
        return final_path
    return dst_path

@app.post("/analyze_video")
async def analyze_video(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...),
    object_code: Optional[str] = Form(None)
):
    if not model:
        return JSONResponse(status_code=500, content={"error": "Model not loaded properly."})
    
    contents = await file.read()
    file_size = len(contents)
    duplicate_classes = check_is_duplicate(file.filename, file_size)
    is_dup = len(duplicate_classes) > 0
    dup_classes_str = ",".join(duplicate_classes)
    
    temp_input = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    try:
        temp_input.write(contents)
        temp_input.flush()
    finally:
        temp_input.close()
        
    temp_output_path = temp_input.name.replace(".mp4", "_output.mp4")
    
    cap = cv2.VideoCapture(temp_input.name)
    if not cap.isOpened():
        remove_file(temp_input.name)
        return JSONResponse(status_code=400, content={"error": "Could not open video file."})
        
    ret, first_frame = cap.read()
    if not ret:
        remove_file(temp_input.name)
        return JSONResponse(status_code=400, content={"error": "Could not read video frames."})
        
    is_good_quality, quality_reason = check_image_quality(first_frame, is_video=True)
    if not is_good_quality:
        cap.release()
        background_tasks.add_task(remove_file, temp_input.name)
        return JSONResponse(content={
            "is_low_quality": True,
            "quality_reason": quality_reason,
            "box_count": 0,
            "pallet_count": 0,
            "is_duplicate": False,
            "duplicate_classes": [],
            "filename": file.filename,
            "file_size": file_size
        })
        
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    out, temp_output_path, width, height = create_video_writer(temp_output_path, fps, width, height)
    if out is None:
        cap.release()
        remove_file(temp_input.name)
        return JSONResponse(
            status_code=500,
            content={"error": "Could not initialize video encoder on this system."},
        )
    
    unique_boxes = set()
    unique_pallets = set()
    
    frame_count = 0
    last_annotated = None
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        frame_count += 1
        
        if frame_count % 2 == 1:
            results = model.track(frame, tracker="bytetrack.yaml", persist=True, augment=True, conf=0.20, iou=0.25, imgsz=1024, max_det=1000, verbose=True)
            result = results[0]
            annotated_frame = result.plot()
            last_annotated = annotated_frame
            
            if result.boxes is not None and result.boxes.id is not None:
                for i, cls_idx in enumerate(result.boxes.cls):
                    class_id = int(cls_idx.item())
                    class_name = result.names[class_id]
                    obj_id = int(result.boxes.id[i].item())
                    
                    if class_name == "box":
                        unique_boxes.add(obj_id)
                    elif class_name == "pallet":
                        unique_pallets.add(obj_id)
        else:
            annotated_frame = last_annotated if last_annotated is not None else frame

        if annotated_frame.shape[1] != width or annotated_frame.shape[0] != height:
            annotated_frame = cv2.resize(annotated_frame, (width, height))
                    
        count_text = f"Total Boxes: {len(unique_boxes)} | Total Pallets: {len(unique_pallets)}"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1
        font_thickness = 2
        text_size = cv2.getTextSize(count_text, font, font_scale, font_thickness)[0]
        text_x = 20
        text_y = height - 30
        cv2.rectangle(annotated_frame, (text_x - 10, text_y - text_size[1] - 10), 
                      (text_x + text_size[0] + 10, text_y + 10), (0, 0, 0), -1)
        cv2.putText(annotated_frame, count_text, (text_x, text_y), font, font_scale, (255, 255, 255), font_thickness)
        
        out.write(annotated_frame)
        
    cap.release()
    out.release()

    if not os.path.exists(temp_output_path) or os.path.getsize(temp_output_path) == 0:
        remove_file(temp_input.name)
        remove_file(temp_output_path)
        return JSONResponse(
            status_code=500,
            content={"error": "Annotated video could not be saved. Try a shorter clip or different format."},
        )

    # OpenCV often writes mp4v/FMP4 which browsers cannot play — re-encode to H.264
    temp_output_path = transcode_video_for_browser(temp_output_path)

    file_name = f"{uuid.uuid4().hex}.mp4"
    final_output_path = f"uploads/{file_name}"
    shutil.move(temp_output_path, os.path.join(UPLOADS_DIR, file_name))
    
    remove_file(temp_input.name)
    
    url = f"http://localhost:8000/{final_output_path}"
    
    final_box = len(unique_boxes)
    final_pallet = len(unique_pallets)
    
    scan_id = None
    if not is_dup:
        scan_id = insert_scan(object_code, file.filename, file_size, final_box, final_pallet, final_output_path)
    
    return JSONResponse(content={
        "box_count": final_box,
        "pallet_count": final_pallet,
        "is_duplicate": is_dup,
        "duplicate_classes": duplicate_classes,
        "annotated_image": url,
        "file_path": final_output_path,
        "scan_id": scan_id,
        "filename": file.filename,
        "file_size": file_size
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
