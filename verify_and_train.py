import os
# pyrefly: ignore [missing-import]
from ultralytics import YOLO

def verify_dataset(base_dir):
    print("--- Verifying Dataset ---")
    splits = ['train', 'valid', 'test']
    is_good = True
    for split in splits:
        img_dir = os.path.join(base_dir, split, 'images')
        lbl_dir = os.path.join(base_dir, split, 'labels')
        if os.path.exists(img_dir):
            imgs = [f for f in os.listdir(img_dir) if f.endswith(('.jpg', '.png', '.jpeg'))]
            print(f"{split} images: {len(imgs)}")
            if len(imgs) == 0:
                is_good = False
        else:
            print(f"{split} images directory missing: {img_dir}")
            if split != 'test': # Test is sometimes optional
                is_good = False
            
        if os.path.exists(lbl_dir):
            lbls = [f for f in os.listdir(lbl_dir) if f.endswith('.txt')]
            print(f"{split} labels: {len(lbls)}")
        else:
            print(f"{split} labels directory missing: {lbl_dir}")
            if split != 'test':
                is_good = False
    print("-------------------------\n")
    return is_good

if __name__ == '__main__':
    base_dir = r"C:\Users\reyan\OneDrive\Desktop\InventoryVerification4"
    if verify_dataset(base_dir):
        print("Dataset looks good. Proceeding to training...")
        
        # Check for existing checkpoint to resume
        checkpoint_path = os.path.join(base_dir, "runs", "train_results_yolo11l", "weights", "last.pt")
        yaml_path = os.path.join(base_dir, "data.yaml")
        
        if os.path.exists(checkpoint_path):
            print(f"Found checkpoint! Resuming training from where it left off...")
            model = YOLO(checkpoint_path)
            model.train(resume=True)
        else:
            print("Starting fresh training with yolo11l.pt")
            model = YOLO('yolo11l.pt') 
            print(f"Training on {yaml_path} for 120 epochs...")
            # Train for 120 epochs with early stopping if no improvement for 10 epochs
            # Added strong augmentations for blur, glare (plastic), and occlusion
            model.train(
                data=yaml_path, 
                epochs=120, 
                imgsz=1024, 
                project=base_dir, 
                name="runs/train_results_yolo11l", 
                exist_ok=True, 
                batch=2, 
                device=0, 
                workers=0, 
                patience=10,
                # --- Augmentations for Blur & Plastic ---
                hsv_v=0.5,       # High value variation for glare/reflections
                hsv_s=0.5,       # Saturation variation
                hsv_h=0.015,     # Hue variation
                bgr=0.1,         # BGR to RGB to help with varying lighting
                blur=0.25,       # 25% chance of applying Gaussian blur (handles blurry uploads)
                median=0.15,     # 15% chance of median blur
                clahe=0.2,       # 20% chance of CLAHE (great for plastic/glare)
                erasing=0.4,     # Random erasing to handle occlusion from plastic tape
                mixup=0.15,      # Mixup helps model learn through semi-transparent overlays
                mosaic=1.0       # Mosaic (default 1.0) is excellent for complex contexts
            )
        
        print("Training complete. Results are saved in 'runs/train_results_yolo11l'.")
    else:
        print("Dataset verification failed. Please check the dataset directories.")
