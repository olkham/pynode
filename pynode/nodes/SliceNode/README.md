# Slice Node - SAHI-style Image Tiling

This module provides nodes for slicing large images into tiles for improved small object detection, based on the SAHI (Slicing Aided Hyper Inference) methodology.

## Nodes

### SliceImageNode

Divides images into overlapping tiles for better detection of small objects in large images.

**Properties:**
- **Output Mode**: 
  - `Array`: All slices in one message (use with Split node)
  - `Split`: Separate message per slice (direct to detector)
- **Auto Slice Resolution**: Automatically calculate slice parameters based on image size
- **Slice Width/Height**: Size of each tile in pixels (default: 640x640)
- **Overlap Width/Height Ratio**: Fractional overlap between tiles (default: 0.2 = 20%)
- **Include Full Image**: Whether to include the original image at full scale in output (for dual-scale detection)

**Output Format (Array mode):**
```json
{
  "payload": {
    "slices": [
      {
        "image": "<encoded_image>",
        "offset": [x, y],
        "bbox": [x1, y1, x2, y2],
        "slice_index": 0,
        "is_full_image": true/false,
        "original_width": 1920,
        "original_height": 1080
      }
    ],
    "slice_count": 5,
    "original_width": 1920,
    "original_height": 1080
  }
}
```

**Output Format (Split mode):**
Each slice sent as separate message with `parts` metadata for collection:
```json
{
  "payload": {
    "image": "<encoded_image>",
    "offset": [x, y],
    ...
  },
  "parts": {
    "index": 0,
    "count": 5,
    "id": "<parent_msg_id>"
  },
  "slice_offset": [x, y],
  "is_full_image": false
}
```

### SliceCollectorNode

Collects detection predictions from multiple image slices and merges them into a single unified result.

**Properties:**
- **Collection Timeout**: Maximum time to wait for all slices (default: 5 seconds)
- **NMS IoU Threshold**: IoU threshold for Non-Maximum Suppression (default: 0.5)
- **Match Metric**: `IoU` or `IoS` (Intersection over Smaller)
- **Class Agnostic NMS**: Whether to apply NMS across all classes or per-class

**Features:**
- Transforms slice-local coordinates to original image coordinates
- Applies NMS to remove duplicate detections from overlapping regions
- Handles full image detections separately and merges with slice detections
- Tracks collections by message ID for concurrent processing

### MergeSlicePredictionsNode

Alternative merge node that expects predictions already collected in a single message.

## Workflow Examples

### Workflow 1: Split Mode (Recommended)

```
[Camera] → [SliceImage (split)] → [YOLO] → [SliceCollector] → [Output]
```

1. SliceImageNode in "Split" mode sends each tile as a separate message
2. YOLO processes each tile
3. SliceCollectorNode collects all predictions and merges them

### Workflow 2: Array Mode

```
[Camera] → [SliceImage (array)] → [Split] → [YOLO] → [SliceCollector] → [Output]
```

1. SliceImageNode outputs all tiles in an array
2. Split node separates them into individual messages
3. YOLO processes each tile
4. SliceCollectorNode collects and merges

### Workflow 3: Batch Processing

```
[Camera] → [SliceImage (array)] → [Custom Processing]
```

Process all slices together in a custom node that can handle arrays.

## SAHI Methodology

The Slicing Aided Hyper Inference approach:

1. **Slice**: Divide large image into smaller overlapping tiles
2. **Detect**: Run object detection on each tile
3. **Transform**: Convert tile-local coordinates to original image coordinates
4. **Merge**: Apply NMS to remove duplicates from overlapping regions

### Why Include Full Image?

Running detection on both tiles AND the full image provides:
- Tiles: Better detection of small objects
- Full image: Better detection of large objects that may be split across tiles

The merge step combines both for comprehensive detection.

## Configuration Tips

### Tile Size
- Match your detector's training resolution (e.g., 640x640 for YOLO)
- Smaller tiles = more tiles but better small object detection
- Larger tiles = fewer tiles but may miss small objects

### Overlap Ratio
- 0.2 (20%) is a good default
- Increase for dense scenes with many small objects
- Decrease for faster processing with fewer duplicates

### NMS Threshold
- 0.5 is a good default
- Lower = more aggressive duplicate removal
- Higher = keep more detections (may have duplicates)

## Dependencies

- OpenCV (cv2)
- NumPy
