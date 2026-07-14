import os
# pyrefly: ignore [missing-import]
from ultralytics import YOLO

def main():
    base_dir = r"C:\Users\reyan\OneDrive\Desktop\InventoryVerification4"
    weights_path = os.path.join(base_dir, "runs", "train_results_yolo11l", "weights", "best.pt")
    yaml_path = os.path.join(base_dir, "data.yaml")

    if not os.path.exists(weights_path):
        print(f"Error: Could not find trained weights at {weights_path}")
        print("Make sure the training process has completed successfully.")
        return

    print(f"Loading trained model from {weights_path}...")
    model = YOLO(weights_path)

    print("Evaluating model on the validation dataset...")
    # Evaluate model performance on the validation set
    # Using device=0 for GPU, and workers=0 to prevent the Windows memory issue
    metrics = model.val(data=yaml_path, device=0, workers=0)
    
    print("\n--- Evaluation Results ---")
    print(f"mAP50-95 (Overall): {metrics.box.map:.4f}") 
    print(f"mAP50:              {metrics.box.map50:.4f}")
    print(f"mAP75:              {metrics.box.map75:.4f}")
    
    print("\nCheck the newly generated 'runs/val' directory (or 'runs/train_resultsN') for visual plots like the confusion matrix and precision-recall curves!")

if __name__ == '__main__':
    main()
