# using ultralytics, download yolov8 model and convert to onnx
from ultralytics import YOLO
model = YOLO("yolov8n.pt")
model.export(format="onnx", opset=20)