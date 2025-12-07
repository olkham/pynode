import numpy as np
from nodes.base_node import BaseNode
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class SupervisionTrackerNode(BaseNode):
    """
    Tracker Node that uses the supervision library for object tracking.
    Supports ByteTrack and other algorithms provided by supervision.
    """
    display_name = 'Supervision Tracker'
    icon = '👀'
    category = 'vision'
    color = '#5C2D91'
    border_color = '#3F1D63'
    text_color = '#FFFFFF'
    
    DEFAULT_CONFIG = {
        'tracker_type': 'bytetrack',
        'track_thresh': '0.25',
        'track_buffer': '30',
        'match_thresh': '0.8',
        'draw_tracks': 'true'
    }
    
    properties = [
        {
            'name': 'tracker_type',
            'label': 'Tracker Type',
            'type': 'select',
            'options': [
                {'value': 'bytetrack', 'label': 'ByteTrack'},
                # Future support for other trackers if needed
            ]
        },
        {
            'name': 'track_thresh',
            'label': 'Tracking Threshold',
            'type': 'text',
            'placeholder': '0.25'
        },
        {
            'name': 'track_buffer',
            'label': 'Track Buffer (frames)',
            'type': 'text',
            'placeholder': '30'
        },
        {
            'name': 'match_thresh',
            'label': 'Match Threshold (IoU)',
            'type': 'text',
            'placeholder': '0.8'
        },
        {
            'name': 'draw_tracks',
            'label': 'Draw Tracks',
            'type': 'select',
            'options': [
                {'value': 'true', 'label': 'Yes'},
                {'value': 'false', 'label': 'No'}
            ]
        }
    ]
    
    def __init__(self, node_id=None, name="sv_tracker"):
        self.tracker = None
        self.box_annotator = None
        self.label_annotator = None
        self._sv_imported = False
        super().__init__(node_id, name)
        
    def _init_tracker(self):
        try:
            import supervision as sv
            self._sv_imported = True
            
            track_thresh = self.get_config_float('track_thresh', 0.25)
            track_buffer = self.get_config_int('track_buffer', 30)
            match_thresh = self.get_config_float('match_thresh', 0.8)
            tracker_type = self.config.get('tracker_type', 'bytetrack')
            
            if tracker_type == 'bytetrack':
                self.tracker = sv.ByteTrack(
                    track_activation_threshold=track_thresh,
                    lost_track_buffer=track_buffer,
                    minimum_matching_threshold=match_thresh,
                    frame_rate=30 # Default assumption
                )
            
            # Initialize annotators for drawing
            self.box_annotator = sv.BoxAnnotator()
            self.label_annotator = sv.LabelAnnotator()
            
        except ImportError:
            self.report_error("supervision library not installed. Run: pip install supervision")
            self._sv_imported = False
        except Exception as e:
            self.report_error(f"Error initializing tracker: {e}")
            
    def configure(self, config):
        # Check if we need to re-init tracker
        old_config = self.config.copy()
        super().configure(config)
        
        if self.tracker is None:
            self._init_tracker()
            return

        # Re-init if critical params changed
        if (old_config.get('tracker_type') != self.config.get('tracker_type') or
            old_config.get('track_thresh') != self.config.get('track_thresh') or
            old_config.get('track_buffer') != self.config.get('track_buffer') or
            old_config.get('match_thresh') != self.config.get('match_thresh')):
            self._init_tracker()

    def on_input(self, msg, input_index=0):
        if not self._sv_imported and self.tracker is None:
            self._init_tracker()
            
        if self.tracker is None:
            self.send(msg)
            return

        try:
            import supervision as sv
            
            payload = msg.get('payload', {})
            if not isinstance(payload, dict):
                self.send(msg)
                return
                
            detections_list = payload.get('detections', [])
            
            # Convert detections list to supervision Detections object
            if not detections_list:
                detections = sv.Detections.empty()
            else:
                xyxy = []
                confidence = []
                class_id = []
                
                for d in detections_list:
                    bbox = d.get('bbox')
                    if bbox and len(bbox) == 4:
                        xyxy.append(bbox)
                        confidence.append(d.get('confidence', 0.0))
                        class_id.append(d.get('class_id', 0))
                
                if xyxy:
                    detections = sv.Detections(
                        xyxy=np.array(xyxy),
                        confidence=np.array(confidence),
                        class_id=np.array(class_id)
                    )
                else:
                    detections = sv.Detections.empty()
            
            # Update tracker
            detections = self.tracker.update_with_detections(detections)
            
            # Extract tracks back to payload format
            tracks = []
            
            # supervision Detections object after tracking has tracker_id
            if detections.tracker_id is not None:
                for i in range(len(detections)):
                    track_id = int(detections.tracker_id[i])
                    cls_id = int(detections.class_id[i])
                    conf = float(detections.confidence[i]) if detections.confidence is not None else 0.0
                    bbox = detections.xyxy[i].tolist()
                    
                    tracks.append({
                        'track_id': track_id,
                        'class_id': cls_id,
                        'confidence': conf,
                        'bbox': bbox,
                        'bbox_wh': [bbox[0], bbox[1], bbox[2]-bbox[0], bbox[3]-bbox[1]]
                    })
            
            payload['tracks'] = tracks
            payload['track_count'] = len(tracks)
            
            # Draw tracks if requested
            if self.get_config_bool('draw_tracks', True) and 'image' in payload:
                image, fmt = self.decode_image(payload['image'])
                if image is not None and fmt is not None:
                    # Use supervision annotators
                    labels = [
                        f"#{tracker_id} {class_id}"
                        for tracker_id, class_id
                        in zip(detections.tracker_id, detections.class_id)
                    ] if detections.tracker_id is not None else []
                    
                    annotated_image = self.box_annotator.annotate(
                        scene=image.copy(),
                        detections=detections
                    )
                    annotated_image = self.label_annotator.annotate(
                        scene=annotated_image,
                        detections=detections,
                        labels=labels
                    )
                    
                    encoded = self.encode_image(annotated_image, fmt)
                    if encoded:
                        payload['image'] = encoded
                        
            self.send(msg)
            
        except Exception as e:
            logger.error(f"Error in SupervisionTrackerNode: {e}", exc_info=True)
            self.report_error(f"Tracker error: {e}")
            self.send(msg)
