"""
Slice Collector Node - collects predictions from multiple image slices and merges them.
Designed to work with SliceImageNode in a slice-detect-merge workflow.
"""

import time
from typing import Any, Dict, List, Optional
from nodes.base_node import BaseNode, Info

_info = Info()
_info.add_text("Collects detection predictions from multiple image slices sent as separate messages, then merges them into a unified result.")
_info.add_header("Inputs")
_info.add_bullets(("Input 0:", "Individual slice prediction messages with slice metadata (from split output mode)"))
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Merged predictions after all slices collected and NMS applied"),
)
_info.add_header("Configuration")
_info.add_bullets(
    ("Timeout:", "Maximum time to wait for all slices before outputting partial results"),
    ("NMS IoU Threshold:", "Threshold for Non-Maximum Suppression"),
    ("Match Metric:", "IoU or IoS for duplicate detection matching"),
    ("Class Agnostic NMS:", "Apply NMS across all classes vs per-class"),
)
_info.add_header("Usage")
_info.add_text("Designed for workflows: SliceImageNode (split mode) → Inference → SliceCollectorNode")


class SliceCollectorNode(BaseNode):
    """
    Slice Collector Node - collects detection predictions from multiple image slices
    and merges them into a single unified result.
    
    This node is designed to pair with SliceImageNode in workflows like:
    
    SliceImageNode -> Split -> YOLONode -> SliceCollectorNode
    
    It tracks slice messages by their msg_id from the original slice operation,
    collects all predictions, transforms coordinates, and applies NMS.
    """
    display_name = 'Slice Collector'
    info = str(_info)
    icon = '📥'
    category = 'vision'
    color = '#FFA07A'
    border_color = '#FF7F50'
    text_color = '#000000'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'timeout': 5.0,
        'nms_threshold': 0.5,
        'match_metric': 'iou',
        'class_agnostic': False,
        'drop_messages': False
    }
    
    properties = [
        {
            'name': 'timeout',
            'label': 'Collection Timeout (seconds)',
            'type': 'number',
            'default': 5.0
        },
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
            'name': 'class_agnostic',
            'label': 'Class Agnostic NMS',
            'type': 'checkbox',
            'default': False
        }
    ]
    
    def __init__(self, node_id=None, name="slice_collector"):
        super().__init__(node_id, name)
        # Track collections by parent message ID
        self._collections: Dict[str, Dict] = {}
    
    def _calculate_iou(self, box1: List[float], box2: List[float]) -> float:
        """Calculate IoU between two bounding boxes in [x1, y1, x2, y2] format."""
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection
        
        return intersection / union if union > 0 else 0.0
    
    def _calculate_ios(self, box1: List[float], box2: List[float]) -> float:
        """Calculate IoS (Intersection over Smaller) between two boxes."""
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2
        
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)
        
        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0
        
        intersection = (x2_i - x1_i) * (y2_i - y1_i)
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        smaller = min(area1, area2)
        
        return intersection / smaller if smaller > 0 else 0.0
    
    def _transform_detections(self, detections: List[Dict], offset: List[int]) -> List[Dict]:
        """Transform detection coordinates from slice-local to original image coords."""
        transformed = []
        offset_x, offset_y = offset
        
        for det in detections:
            new_det = det.copy()
            bbox = det.get('bbox', [])
            
            if len(bbox) >= 4:
                x1, y1, x2, y2 = bbox[:4]
                new_det['bbox'] = [x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y]
                new_det['slice_offset'] = offset
            
            transformed.append(new_det)
        
        return transformed
    
    def _nms(self, detections: List[Dict], nms_threshold: float, 
             match_metric: str = 'iou', class_agnostic: bool = False) -> List[Dict]:
        """Apply Non-Maximum Suppression to remove duplicate detections."""
        if not detections:
            return []
        
        sorted_dets = sorted(detections, key=lambda x: x.get('confidence', 0), reverse=True)
        metric_fn = self._calculate_iou if match_metric == 'iou' else self._calculate_ios
        
        if class_agnostic:
            groups = {'all': sorted_dets}
        else:
            groups: Dict[Any, List[Dict]] = {}
            for det in sorted_dets:
                class_id = det.get('class_id', det.get('class_name', 'unknown'))
                if class_id not in groups:
                    groups[class_id] = []
                groups[class_id].append(det)
        
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
                    
                    if metric_fn(bbox_i, bbox_j) > nms_threshold:
                        should_keep = False
                        break
                
                if should_keep:
                    keep_indices.append(i)
            
            kept.extend([group[i] for i in keep_indices])
        
        return kept
    
    def _cleanup_expired(self):
        """Remove expired collections."""
        timeout = self.get_config_float('timeout', 5.0)
        current_time = time.time()
        expired = [k for k, v in self._collections.items() 
                   if current_time - v['start_time'] > timeout]
        for k in expired:
            del self._collections[k]
    
    def _process_collection(self, collection_id: str) -> Optional[Dict]:
        """Process a complete collection and return merged result."""
        collection = self._collections.get(collection_id)
        if not collection:
            return None
        
        nms_threshold = self.get_config_float('nms_threshold', 0.5)
        match_metric = self.config.get('match_metric', 'iou')
        class_agnostic = self.get_config_bool('class_agnostic', False)
        
        all_detections = []
        full_image_detections = []
        
        for slice_data in collection['slices'].values():
            offset = slice_data.get('offset', [0, 0])
            detections = slice_data.get('detections', [])
            is_full_image = slice_data.get('is_full_image', False)
            
            if is_full_image:
                full_image_detections.extend(detections)
            else:
                transformed = self._transform_detections(detections, offset)
                all_detections.extend(transformed)
        
        # Apply NMS
        merged = self._nms(all_detections, nms_threshold, match_metric, class_agnostic)
        
        # Combine with full image detections if present
        if full_image_detections:
            combined = merged + full_image_detections
            final_detections = self._nms(combined, nms_threshold, match_metric, class_agnostic)
        else:
            final_detections = merged
        
        # Sort by confidence
        final_detections = sorted(final_detections, key=lambda x: x.get('confidence', 0), reverse=True)
        
        return {
            'detections': final_detections,
            'detection_count': len(final_detections),
            'original_width': collection.get('original_width', 0),
            'original_height': collection.get('original_height', 0),
            'slice_count': len(collection['slices']),
            'bbox_format': 'xyxy',
            'image': collection.get('image')
        }
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """
        Collect slice predictions and merge when complete.
        
        Expected msg format (from Split of SliceImageNode output, processed by YOLO):
        {
            'payload': {
                'image': ...,
                'detections': [...],
                ...
            },
            'parts': {
                'index': int,
                'count': int,
                'id': str  # Parent message ID
            },
            'slice_offset': [x, y],  # From SliceImageNode
            'slice_index': int,
            'is_full_image': bool,
            'original_width': int,
            'original_height': int
        }
        """
        self._cleanup_expired()
        
        payload = msg.get('payload', {})
        parts = msg.get('parts', {})
        
        # Get collection ID (from parts or generate one)
        collection_id = parts.get('id', msg.get('_msgid', 'default'))
        expected_count = parts.get('count', 1)
        slice_index = parts.get('index', msg.get('slice_index', 0))
        
        # Get slice metadata (check message level first, then payload)
        offset = msg.get('slice_offset', payload.get('offset', [0, 0]) if isinstance(payload, dict) else [0, 0])
        slice_bbox = msg.get('slice_bbox', payload.get('bbox', None) if isinstance(payload, dict) else None)
        is_full_image = msg.get('is_full_image', payload.get('is_full_image', False) if isinstance(payload, dict) else False)
        original_width = msg.get('original_width', payload.get('original_width', 0) if isinstance(payload, dict) else 0)
        original_height = msg.get('original_height', payload.get('original_height', 0) if isinstance(payload, dict) else 0)
        
        # Get detections
        if isinstance(payload, dict):
            detections = payload.get('detections', [])
            image = payload.get('image')
        else:
            detections = []
            image = None
        
        # Initialize collection if needed
        if collection_id not in self._collections:
            self._collections[collection_id] = {
                'start_time': time.time(),
                'expected_count': expected_count,
                'slices': {},
                'original_width': original_width,
                'original_height': original_height,
                'original_msg': msg.copy(),
                'image': None
            }
        
        collection = self._collections[collection_id]
        
        # Store slice data
        collection['slices'][slice_index] = {
            'detections': detections,
            'offset': offset,
            'is_full_image': is_full_image
        }
        
        # Store full image if this is the full image slice
        if is_full_image and image is not None:
            collection['image'] = image
        
        # Update dimensions if available
        if original_width > 0:
            collection['original_width'] = original_width
        if original_height > 0:
            collection['original_height'] = original_height
        
        # Check if complete
        if len(collection['slices']) >= collection['expected_count']:
            result = self._process_collection(collection_id)
            
            if result:
                out_msg = collection['original_msg'].copy()
                out_msg['payload'] = result
                out_msg['topic'] = out_msg.get('topic', 'merged_predictions')
                
                # Clean up parts since we've merged
                out_msg.pop('parts', None)
                
                self.send(out_msg)
            
            # Clean up
            del self._collections[collection_id]
