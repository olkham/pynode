"""
Merge Slice Predictions Node - combines predictions from image slices.
Based on SAHI (Slicing Aided Hyper Inference) methodology for prediction merging.
"""

import numpy as np
from typing import Any, Dict, List, Tuple, Optional
from pynode.nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Combines detection predictions from multiple image slices back into a unified result. Based on SAHI methodology for prediction merging.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Array message containing slice predictions with offset metadata"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Merged predictions with coordinates transformed to original image space"),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("NMS IoU Threshold:", "Threshold for Non-Maximum Suppression to remove duplicates"),
    ("Match Metric:", "IoU (Intersection over Union) or IoS (Intersection over Smaller)"),
    ("Match Threshold:", "Threshold for considering detections as duplicates"),
    ("Class Agnostic NMS:", "Apply NMS across all classes vs per-class"),
)


class MergeSlicePredictionsNode(BaseNode):
    """
    Merge Slice Predictions Node - combines detection predictions from multiple
    image slices back into a single unified result.
    
    Handles coordinate transformation from slice-local to original image coordinates,
    and applies Non-Maximum Suppression (NMS) to remove duplicate detections
    from overlapping regions.
    """
    display_name = 'Merge Predictions'
    info = str(_info)
    icon = '🔗'
    category = 'vision'
    color = '#FF6B6B'
    border_color = '#EE5A5A'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'nms_threshold': 0.5,
        'match_metric': 'iou',
        'match_threshold': 0.5,
        'class_agnostic': False,
        'drop_messages': False
    }
    
    properties = [
        {
            'name': 'nms_threshold',
            'label': 'NMS IoU Threshold',
            'type': 'number',
            'default': 0.5
        },
        {
            'name': 'match_metric',
            'label': 'Match Metric',
            'type': 'select',
            'options': [
                {'value': 'iou', 'label': 'IoU (Intersection over Union)'},
                {'value': 'ios', 'label': 'IoS (Intersection over Smaller)'}
            ],
            'default': 'iou'
        },
        {
            'name': 'match_threshold',
            'label': 'Match Threshold',
            'type': 'number',
            'default': 0.5
        },
        {
            'name': 'class_agnostic',
            'label': 'Class Agnostic NMS',
            'type': 'checkbox',
            'default': False
        }
    ]
    
    def __init__(self, node_id=None, name="merge_predictions"):
        super().__init__(node_id, name)
        self._pending_slices: Dict[str, Dict] = {}  # msg_id -> collected slice data
    
    def _calculate_iou(self, box1: List[float], box2: List[float]) -> float:
        """
        Calculate Intersection over Union (IoU) between two bounding boxes.
        Boxes are in [x1, y1, x2, y2] format.
        """
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        # Calculate intersection
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        
        # Calculate areas
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        
        # Calculate union
        union = area1 + area2 - intersection
        
        if union <= 0:
            return 0.0
        
        return intersection / union
    
    def _calculate_ios(self, box1: List[float], box2: List[float]) -> float:
        """
        Calculate Intersection over Smaller area (IoS) between two bounding boxes.
        Useful for detecting when a smaller box is inside a larger one.
        """
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        # Calculate intersection
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        
        # Calculate areas
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        
        # Smaller area
        smaller = min(area1, area2)
        
        if smaller <= 0:
            return 0.0
        
        return intersection / smaller
    
    def _transform_detections(
        self,
        detections: List[Dict],
        offset: List[int]
    ) -> List[Dict]:
        """
        Transform detection coordinates from slice-local to original image coordinates.
        """
        transformed = []
        offset_x, offset_y = offset
        
        for det in detections:
            new_det = det.copy()
            bbox = det.get('bbox', [])
            
            if len(bbox) >= 4:
                # Transform bounding box coordinates
                x1, y1, x2, y2 = bbox[:4]
                new_det['bbox'] = [
                    x1 + offset_x,
                    y1 + offset_y,
                    x2 + offset_x,
                    y2 + offset_y
                ]
                # Store original slice-local bbox for reference
                new_det['slice_bbox'] = bbox[:4]
                new_det['slice_offset'] = offset
            
            transformed.append(new_det)
        
        return transformed
    
    def _nms(
        self,
        detections: List[Dict],
        nms_threshold: float,
        match_metric: str = 'iou',
        class_agnostic: bool = False
    ) -> List[Dict]:
        """
        Apply Non-Maximum Suppression to remove duplicate detections.
        
        Args:
            detections: List of detection dicts with 'bbox' and 'confidence'
            nms_threshold: IoU/IoS threshold for suppression
            match_metric: 'iou' or 'ios'
            class_agnostic: If True, NMS across all classes; if False, per-class NMS
        
        Returns:
            Filtered list of detections
        """
        if not detections:
            return []
        
        # Sort by confidence (highest first)
        sorted_dets = sorted(detections, key=lambda x: x.get('confidence', 0), reverse=True)
        
        # Select metric function
        metric_fn = self._calculate_iou if match_metric == 'iou' else self._calculate_ios
        
        # Group by class if not class-agnostic
        if class_agnostic:
            groups = {'all': sorted_dets}
        else:
            groups: Dict[Any, List[Dict]] = {}
            for det in sorted_dets:
                class_id = det.get('class_id', det.get('class_name', 'unknown'))
                if class_id not in groups:
                    groups[class_id] = []
                groups[class_id].append(det)
        
        # Apply NMS per group
        kept = []
        for class_id, group in groups.items():
            keep_indices = []
            
            for i, det in enumerate(group):
                should_keep = True
                bbox_i = det.get('bbox', [])
                
                if len(bbox_i) < 4:
                    continue
                
                for j in keep_indices:
                    bbox_j = group[j].get('bbox', [])
                    if len(bbox_j) < 4:
                        continue
                    
                    overlap = metric_fn(bbox_i, bbox_j)
                    if overlap > nms_threshold:
                        should_keep = False
                        break
                
                if should_keep:
                    keep_indices.append(i)
            
            kept.extend([group[i] for i in keep_indices])
        
        return kept
    
    def _greedy_nmm(
        self,
        detections: List[Dict],
        match_threshold: float,
        match_metric: str = 'iou'
    ) -> List[Dict]:
        """
        Greedy Non-Maximum Merging - merges overlapping detections of same class.
        
        Instead of suppressing, this merges overlapping boxes by averaging
        their coordinates, weighted by confidence.
        """
        if not detections:
            return []
        
        # Sort by confidence (highest first)
        sorted_dets = sorted(detections, key=lambda x: x.get('confidence', 0), reverse=True)
        
        metric_fn = self._calculate_iou if match_metric == 'iou' else self._calculate_ios
        
        merged = []
        used = set()
        
        for i, det_i in enumerate(sorted_dets):
            if i in used:
                continue
            
            bbox_i = det_i.get('bbox', [])
            if len(bbox_i) < 4:
                continue
            
            class_i = det_i.get('class_id', det_i.get('class_name', 'unknown'))
            conf_i = det_i.get('confidence', 0)
            
            # Find all matching detections
            matches = [(i, det_i, conf_i)]
            
            for j, det_j in enumerate(sorted_dets[i+1:], start=i+1):
                if j in used:
                    continue
                
                class_j = det_j.get('class_id', det_j.get('class_name', 'unknown'))
                if class_i != class_j:
                    continue
                
                bbox_j = det_j.get('bbox', [])
                if len(bbox_j) < 4:
                    continue
                
                overlap = metric_fn(bbox_i, bbox_j)
                if overlap > match_threshold:
                    matches.append((j, det_j, det_j.get('confidence', 0)))
                    used.add(j)
            
            # Merge matched detections
            if len(matches) == 1:
                merged.append(det_i)
            else:
                # Weighted average of bounding boxes
                total_conf = sum(m[2] for m in matches)
                if total_conf > 0:
                    merged_bbox = [0, 0, 0, 0]
                    for idx, det, conf in matches:
                        bbox = det.get('bbox', [0, 0, 0, 0])
                        weight = conf / total_conf
                        for k in range(4):
                            merged_bbox[k] += bbox[k] * weight
                    
                    merged_det = det_i.copy()
                    merged_det['bbox'] = merged_bbox
                    merged_det['confidence'] = max(m[2] for m in matches)
                    merged_det['merged_count'] = len(matches)
                    merged.append(merged_det)
                else:
                    merged.append(det_i)
            
            used.add(i)
        
        return merged
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Process incoming slice predictions and merge them.
        
        Expected input format (from SliceImageNode + detection):
        {
            'payload': {
                'slice_predictions': [
                    {
                        'slice_index': 0,
                        'offset': [x, y],
                        'detections': [...],
                        'is_full_image': bool
                    },
                    ...
                ],
                'original_width': int,
                'original_height': int
            }
        }
        """
        payload = msg.get('payload', {})
        
        if not isinstance(payload, dict):
            self.report_error("Payload must be a dictionary")
            return
        
        slice_predictions = payload.get('slice_predictions', [])
        
        if not slice_predictions:
            # Try alternative format - direct detections array with offsets
            slices = payload.get('slices', [])
            if slices:
                slice_predictions = []
                for s in slices:
                    if 'detections' in s:
                        slice_predictions.append(s)
        
        if not slice_predictions:
            self.report_error("No slice predictions found in payload")
            return
        
        # Get configuration
        nms_threshold = self.get_config_float('nms_threshold', 0.5)
        match_metric = self.config.get('match_metric', 'iou')
        match_threshold = self.get_config_float('match_threshold', 0.5)
        class_agnostic = self.get_config_bool('class_agnostic', False)
        
        # Collect all detections, transforming coordinates
        all_detections = []
        full_image_detections = []
        
        for slice_pred in slice_predictions:
            offset = slice_pred.get('offset', [0, 0])
            detections = slice_pred.get('detections', [])
            is_full_image = slice_pred.get('is_full_image', False)
            
            if is_full_image:
                # Store full image detections separately
                full_image_detections.extend(detections)
            else:
                # Transform slice-local coordinates to original image coordinates
                transformed = self._transform_detections(detections, offset)
                all_detections.extend(transformed)
        
        # Apply NMS to slice detections
        merged_detections = self._nms(
            all_detections,
            nms_threshold,
            match_metric,
            class_agnostic
        )
        
        # Optionally combine with full image detections
        if full_image_detections:
            # Add full image detections and run NMS again
            combined = merged_detections + full_image_detections
            final_detections = self._nms(
                combined,
                nms_threshold,
                match_metric,
                class_agnostic
            )
        else:
            final_detections = merged_detections
        
        # Sort by confidence
        final_detections = sorted(
            final_detections,
            key=lambda x: x.get('confidence', 0),
            reverse=True
        )
        
        # Prepare output
        original_width = payload.get('original_width', 0)
        original_height = payload.get('original_height', 0)
        
        out_msg = msg.copy()
        out_msg['payload'] = {
            'detections': final_detections,
            'detection_count': len(final_detections),
            'original_width': original_width,
            'original_height': original_height,
            'slice_count': len(slice_predictions),
            'bbox_format': 'xyxy'
        }
        
        # Preserve image if present
        if 'image' in payload:
            out_msg['payload']['image'] = payload['image']
        
        out_msg['topic'] = msg.get('topic', 'merged_predictions')
        
        self.send(out_msg)
