# Inventory AI

**Inventory AI** is a full-stack YOLO object detection application for warehouse auditing. Pre-trained on over 15,000 images, it instantly counts boxes and pallets from photos or videos to verify ERP data, featuring an automated self-training loop powered by Gemini to continually adapt to new environments.

## Features
- 🚀 **Full-Stack Object Detection:** Seamlessly upload photos and videos via the React frontend for real-time inference on the FastAPI backend.
- 🎯 **Trained on 15k+ Images:** Powered by a highly robust, custom-trained YOLO model capable of accurately detecting warehouse boxes and pallets at scale.
- 🔄 **Continuous AI Learning:** Features a zero-shot auto-training loop using Gemini 3.5 Flash to automatically annotate new edge cases and fine-tune the YOLO model on the fly.
- 📊 **ERP Verification:** Upload your ERP CSV to instantly spot discrepancies (missing or surplus inventory).

## Tech Stack
- **Frontend:** React, TypeScript, Vite
- **Backend:** FastAPI, Python, SQLite
- **Machine Learning:** YOLO (Ultralytics), OpenCV, Google Gemini API
