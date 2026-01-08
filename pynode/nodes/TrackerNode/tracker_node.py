import numpy as np
from pynode.nodes.base_node import BaseNode, Info, MessageKeys
import time
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

_info = Info()
_info.add_text("Implements ByteTrack algorithm to track detected objects across video frames. Uses Kalman filtering for motion prediction and IoU-based association to maintain consistent track IDs.")
_info.add_header("Inputs")
_info.add_bullets(
    ("Input 0:", "Message with payload containing 'detections' array (from object detector) and optional 'image' for visualization")
)
_info.add_header("Outputs")
_info.add_bullets(
    ("Output 0:", "Message with 'tracks' array added to payload, each track containing track_id, class_id, confidence, bbox [x1,y1,x2,y2], and bbox_wh [x,y,w,h]")
)
_info.add_header("Properties")
_info.add_bullets(
    ("Tracking Threshold:", "Minimum confidence score for high-priority detections (default: 0.5)"),
    ("Track Buffer:", "Number of frames to keep lost tracks before removal (default: 30)"),
    ("Match Threshold:", "IoU threshold for associating detections with tracks (default: 0.8)"),
    ("Draw Tracks:", "Annotate image with bounding boxes and track IDs")
)

class KalmanFilter:
    """
    A simple Kalman filter for tracking bounding boxes in image space.
    The 8-dimensional state space is [x, y, a, h, vx, vy, va, vh], where the x, y is the center of the box,
    a is the aspect ratio, and h is the height.
    """
    def __init__(self):
        ndim, dt = 4, 1.
        
        # Create Kalman filter model matrices
        self._motion_mat = np.eye(2 * ndim, 2 * ndim)
        for i in range(ndim):
            self._motion_mat[i, ndim + i] = dt
            
        self._update_mat = np.eye(ndim, 2 * ndim)
        
        self._std_weight_position = 1. / 20
        self._std_weight_velocity = 1. / 160
        
    def initiate(self, measurement):
        """Create track from unassociated measurement.
        
        Parameters
        ----------
        measurement : ndarray
            Bounding box coordinates (x, y, a, h) with center position (x, y),
            aspect ratio a, and height h.
            
        Returns
        -------
        (ndarray, ndarray)
            Returns the mean vector (8 dimensional) and covariance matrix (8x8 dimensional) of the new track.
        """
        mean_pos = measurement
        mean_vel = np.zeros_like(mean_pos)
        mean = np.r_[mean_pos, mean_vel]

        std = [
            2 * self._std_weight_position * measurement[3],
            2 * self._std_weight_position * measurement[3],
            1e-2,
            2 * self._std_weight_position * measurement[3],
            10 * self._std_weight_velocity * measurement[3],
            10 * self._std_weight_velocity * measurement[3],
            1e-5,
            10 * self._std_weight_velocity * measurement[3]
        ]
        covariance = np.diag(np.square(std))
        return mean, covariance

    def predict(self, mean, covariance):
        """Run Kalman filter prediction step.
        
        Parameters
        ----------
        mean : ndarray
            The 8 dimensional mean vector of the object state at the previous time step.
        covariance : ndarray
            The 8x8 dimensional covariance matrix of the object state at the previous time step.
            
        Returns
        -------
        (ndarray, ndarray)
            Returns the mean vector and covariance matrix of the predicted state.
        """
        std_pos = [
            self._std_weight_position * mean[3],
            self._std_weight_position * mean[3],
            1e-2,
            self._std_weight_position * mean[3]
        ]
        std_vel = [
            self._std_weight_velocity * mean[3],
            self._std_weight_velocity * mean[3],
            1e-5,
            self._std_weight_velocity * mean[3]
        ]
        motion_cov = np.diag(np.square(np.r_[std_pos, std_vel]))

        mean = np.dot(self._motion_mat, mean)
        covariance = np.linalg.multi_dot((
            self._motion_mat, covariance, self._motion_mat.T
        )) + motion_cov

        return mean, covariance

    def project(self, mean, covariance):
        """Project state distribution to measurement space.
        
        Parameters
        ----------
        mean : ndarray
            The state's mean vector (8 dimensional).
        covariance : ndarray
            The state's covariance matrix (8x8 dimensional).
            
        Returns
        -------
        (ndarray, ndarray)
            Returns the projected mean and covariance matrix of the given state estimate.
        """
        std = [
            self._std_weight_position * mean[3],
            self._std_weight_position * mean[3],
            1e-1,
            self._std_weight_position * mean[3]
        ]
        innovation_cov = np.diag(np.square(std))

        mean = np.dot(self._update_mat, mean)
        covariance = np.linalg.multi_dot((
            self._update_mat, covariance, self._update_mat.T
        )) + innovation_cov

        return mean, covariance

    def update(self, mean, covariance, measurement):
        """Run Kalman filter correction step.
        
        Parameters
        ----------
        mean : ndarray
            The predicted state's mean vector (8 dimensional).
        covariance : ndarray
            The state's covariance matrix (8x8 dimensional).
        measurement : ndarray
            The 4 dimensional measurement vector (x, y, a, h), where (x, y) is the center position,
            a the aspect ratio, and h the height of the bounding box.
            
        Returns
        -------
        (ndarray, ndarray)
            Returns the measurement-corrected state distribution.
        """
        projected_mean, projected_cov = self.project(mean, covariance)

        try:
            # Solve S * K^T = H * P for K^T
            # S = projected_cov
            # B = (H * P)^T = P * H^T
            B = np.dot(covariance, self._update_mat.T).T
            kalman_gain = np.linalg.solve(projected_cov, B).T
        except np.linalg.LinAlgError:
            return mean, covariance

        innovation = measurement - projected_mean

        new_mean = mean + np.dot(innovation, kalman_gain.T)
        
        # P_new = P - K * S * K^T
        new_covariance = covariance - np.linalg.multi_dot((
            kalman_gain, projected_cov, kalman_gain.T
        ))
        return new_mean, new_covariance


class STrack:
    """
    Single Track class for ByteTrack.
    """
    shared_kalman = KalmanFilter()

    def __init__(self, tlwh, score, class_id):
        # wait activate
        self._tlwh = np.asarray(tlwh, dtype=np.float32)
        self.kalman_filter = None
        self.mean, self.covariance = None, None
        self.is_activated = False

        self.score = score
        self.class_id = class_id
        self.tracklet_len = 0
        self.track_id = 0
        self.state = 1 # TrackState.New
        self.frame_id = 0
        self.start_frame = 0

    @property
    def end_frame(self):
        return self.frame_id

    @property
    def tlbr(self):
        """Convert bounding box to format `(min x, min y, max x, max y)`, i.e.,
        `(top left, bottom right)`.
        """
        ret = self.tlwh.copy()
        ret[2:] += ret[:2]
        return ret

    @property
    def tlwh(self):
        """Get current position in bounding box format `(top left x, top left y,
        width, height)`.
        """
        if self.mean is None:
            return self._tlwh.copy()
        ret = self.mean[:4].copy()
        ret[2] *= ret[3]
        ret[:2] -= ret[2:] / 2
        return ret

    def predict(self):
        mean_state = self.mean.copy()
        if self.state != 1: # TrackState.New
            self.mean, self.covariance = self.shared_kalman.predict(mean_state, self.covariance)

    def activate(self, kalman_filter, frame_id):
        """Start a new tracklet"""
        self.kalman_filter = kalman_filter
        self.track_id = self.next_id()
        self.mean, self.covariance = self.kalman_filter.initiate(self.tlwh_to_xyah(self._tlwh))

        self.tracklet_len = 0
        self.state = 2 # TrackState.Tracked
        if frame_id == 1:
            self.is_activated = True
        self.frame_id = frame_id
        self.start_frame = frame_id

    def re_activate(self, new_track, frame_id, new_id=False):
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, self.tlwh_to_xyah(new_track.tlwh)
        )
        self.tracklet_len = 0
        self.state = 2 # TrackState.Tracked
        self.is_activated = True
        self.frame_id = frame_id
        if new_id:
            self.track_id = self.next_id()
        self.score = new_track.score
        self.class_id = new_track.class_id

    def update(self, new_track, frame_id):
        """
        Update a matched track
        :type new_track: STrack
        :type frame_id: int
        :type update_feature: bool
        :return:
        """
        self.frame_id = frame_id
        self.tracklet_len += 1

        new_tlwh = new_track.tlwh
        self.mean, self.covariance = self.kalman_filter.update(
            self.mean, self.covariance, self.tlwh_to_xyah(new_tlwh)
        )
        self.state = 2 # TrackState.Tracked
        self.is_activated = True

        self.score = new_track.score
        self.class_id = new_track.class_id

    @staticmethod
    def tlwh_to_xyah(tlwh):
        """Convert bounding box to format `(center x, center y, aspect ratio,
        height)`, where the aspect ratio is `width / height`.
        """
        ret = np.asarray(tlwh).copy()
        ret[:2] += ret[2:] / 2
        ret[2] /= ret[3]
        return ret

    @staticmethod
    def next_id():
        if not hasattr(STrack, '_count'):
            STrack._count = 0
        STrack._count += 1
        return STrack._count


class ByteTracker:
    def __init__(self, track_thresh=0.5, track_buffer=30, match_thresh=0.8, frame_rate=30):
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        self.frame_id = 0
        self.det_thresh = track_thresh + 0.1
        self.buffer_size = int(frame_rate / 30.0 * track_buffer)
        self.max_time_lost = self.buffer_size
        self.kalman_filter = KalmanFilter()

        self.tracked_stracks = []
        self.lost_stracks = []
        self.removed_stracks = []

    def update(self, output_results):
        self.frame_id += 1
        activated_stracks = []
        refind_stracks = []
        lost_stracks = []
        removed_stracks = []

        # Parse detections
        # output_results is list of [x1, y1, x2, y2, score, class_id]
        if len(output_results) == 0:
            scores = np.array([], dtype=np.float32)
            bboxes = np.array([], dtype=np.float32)
            classes = np.array([], dtype=np.float32)
        else:
            output_results = np.array(output_results)
            scores = output_results[:, 4]
            bboxes = output_results[:, :4]  # x1y1x2y2
            classes = output_results[:, 5]

        remain_inds = scores > self.track_thresh
        inds_low = scores > 0.1
        inds_high = scores < self.track_thresh

        inds_second = np.logical_and(inds_low, inds_high)
        
        dets_second = []
        dets = []
        
        if len(bboxes) > 0:
            # High confidence detections
            dets = [STrack(ByteTracker.tlbr_to_tlwh(tlbr), score, cls_id) 
                   for tlbr, score, cls_id in zip(bboxes[remain_inds], scores[remain_inds], classes[remain_inds])]
            
            # Low confidence detections
            dets_second = [STrack(ByteTracker.tlbr_to_tlwh(tlbr), score, cls_id) 
                          for tlbr, score, cls_id in zip(bboxes[inds_second], scores[inds_second], classes[inds_second])]

        # Add unconfirmed tracks to tracked_stracks list for matching
        unconfirmed = []
        tracked_stracks = []  # type: list[STrack]
        for track in self.tracked_stracks:
            if not track.is_activated:
                unconfirmed.append(track)
            else:
                tracked_stracks.append(track)

        # Step 2: First association, with high score detection boxes
        strack_pool = join_stracks(tracked_stracks, self.lost_stracks)
        
        # Predict the current location with KF
        for strack in strack_pool:
            strack.predict()

        dists = iou_distance(strack_pool, dets)
        
        # Use greedy matching instead of Hungarian algorithm to avoid scipy dependency
        matches, u_track, u_detection = greedy_match(dists, thresh=self.match_thresh)

        for itracked, idet in matches:
            track = strack_pool[itracked]
            det = dets[idet]
            if track.state == 2: # TrackState.Tracked
                track.update(det, self.frame_id)
                activated_stracks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False)
                refind_stracks.append(track)

        # Step 3: Second association, with low score detection boxes
        r_tracked_stracks = [strack_pool[i] for i in u_track if strack_pool[i].state == 2]
        dists = iou_distance(r_tracked_stracks, dets_second)
        
        matches, u_track, u_detection_second = greedy_match(dists, thresh=0.5)

        for itracked, idet in matches:
            track = r_tracked_stracks[itracked]
            det = dets_second[idet]
            if track.state == 2:
                track.update(det, self.frame_id)
                activated_stracks.append(track)
            else:
                track.re_activate(det, self.frame_id, new_id=False)
                refind_stracks.append(track)

        for it in u_track:
            track = r_tracked_stracks[it]
            if not track.state == 3: # TrackState.Lost
                track.state = 3 # TrackState.Lost
                lost_stracks.append(track)

        # Deal with unconfirmed tracks, usually tracks with only one beginning frame
        detections = [dets[i] for i in u_detection]
        dists = iou_distance(unconfirmed, detections)
        
        matches, u_unconfirmed, u_detection = greedy_match(dists, thresh=0.7)

        for itracked, idet in matches:
            unconfirmed[itracked].update(detections[idet], self.frame_id)
            activated_stracks.append(unconfirmed[itracked])

        for it in u_unconfirmed:
            track = unconfirmed[it]
            track.state = 4 # TrackState.Removed
            removed_stracks.append(track)

        # Step 4: Init new stracks
        for inew in u_detection:
            track = detections[inew]
            if track.score < self.det_thresh:
                continue
            track.activate(self.kalman_filter, self.frame_id)
            activated_stracks.append(track)

        # Step 5: Update state
        for track in self.lost_stracks:
            if self.frame_id - track.end_frame > self.max_time_lost:
                track.state = 4 # TrackState.Removed
                removed_stracks.append(track)

        self.tracked_stracks = [t for t in self.tracked_stracks if t.state == 2]
        self.tracked_stracks = join_stracks(self.tracked_stracks, activated_stracks)
        self.tracked_stracks = join_stracks(self.tracked_stracks, refind_stracks)
        self.lost_stracks = sub_stracks(self.lost_stracks, self.tracked_stracks)
        self.lost_stracks.extend(lost_stracks)
        self.lost_stracks = sub_stracks(self.lost_stracks, self.removed_stracks)
        self.removed_stracks.extend(removed_stracks)
        self.tracked_stracks, self.lost_stracks = remove_duplicate_stracks(self.tracked_stracks, self.lost_stracks)
        
        # Return output tracks
        output_stracks = [track for track in self.tracked_stracks if track.is_activated]
        return output_stracks

    @staticmethod
    def tlbr_to_tlwh(tlbr):
        ret = np.asarray(tlbr).copy()
        ret[2:] -= ret[:2]
        return ret


def join_stracks(tlista, tlistb):
    exists = {}
    res = []
    for t in tlista:
        exists[t.track_id] = 1
        res.append(t)
    for t in tlistb:
        tid = t.track_id
        if not exists.get(tid, 0):
            exists[tid] = 1
            res.append(t)
    return res


def sub_stracks(tlista, tlistb):
    stracks = {}
    for t in tlista:
        stracks[t.track_id] = t
    for t in tlistb:
        tid = t.track_id
        if stracks.get(tid, 0):
            del stracks[tid]
    return list(stracks.values())


def remove_duplicate_stracks(stracksa, stracksb):
    pdist = iou_distance(stracksa, stracksb)
    pairs = np.where(pdist < 0.15)
    dupa, dupb = pairs
    for a, b in zip(dupa, dupb):
        timea = stracksa[a].frame_id - stracksa[a].start_frame
        timeb = stracksb[b].frame_id - stracksb[b].start_frame
        if timea > timeb:
            dupb = list(dupb)
            dupb.remove(b)
            dupb = tuple(dupb)
        else:
            dupa = list(dupa)
            dupa.remove(a)
            dupa = tuple(dupa)
    res_a = [t for i, t in enumerate(stracksa) if not i in dupa]
    res_b = [t for i, t in enumerate(stracksb) if not i in dupb]
    return res_a, res_b


def iou_distance(atracks, btracks):
    """
    Compute cost based on IoU
    :type atracks: list[STrack]
    :type btracks: list[STrack]
    :rtype cost_matrix np.ndarray
    """
    if (len(atracks) == 0 and len(btracks) == 0):
        return np.empty((0, 0))
    
    atlbrs = [track.tlbr for track in atracks]
    btlbrs = [track.tlbr for track in btracks]
    
    ious = np.zeros((len(atlbrs), len(btlbrs)), dtype=np.float32)
    if len(atlbrs) * len(btlbrs) == 0:
        return ious

    ious = bbox_ious(np.ascontiguousarray(atlbrs, dtype=np.float32), 
                     np.ascontiguousarray(btlbrs, dtype=np.float32))
    cost_matrix = 1 - ious
    return cost_matrix


def bbox_ious(boxes1, boxes2):
    """
    Compute IOU between two sets of boxes
    """
    b1_x1, b1_y1, b1_x2, b1_y2 = boxes1[:, 0], boxes1[:, 1], boxes1[:, 2], boxes1[:, 3]
    b2_x1, b2_y1, b2_x2, b2_y2 = boxes2[:, 0], boxes2[:, 1], boxes2[:, 2], boxes2[:, 3]

    inter_rect_x1 = np.maximum(b1_x1[:, None], b2_x1)
    inter_rect_y1 = np.maximum(b1_y1[:, None], b2_y1)
    inter_rect_x2 = np.minimum(b1_x2[:, None], b2_x2)
    inter_rect_y2 = np.minimum(b1_y2[:, None], b2_y2)

    inter_area = np.maximum(inter_rect_x2 - inter_rect_x1, 0) * \
                 np.maximum(inter_rect_y2 - inter_rect_y1, 0)

    b1_area = (b1_x2 - b1_x1) * (b1_y2 - b1_y1)
    b2_area = (b2_x2 - b2_x1) * (b2_y2 - b2_y1)

    iou = inter_area / (b1_area[:, None] + b2_area - inter_area + 1e-16)
    return iou


def greedy_match(distance_matrix, thresh):
    """
    Greedy matching to replace linear_assignment (Hungarian algorithm)
    when scipy is not available.
    """
    if distance_matrix.size == 0:
        return [], list(range(distance_matrix.shape[0])), list(range(distance_matrix.shape[1]))

    matched_indices = []
    
    # Work on a copy
    dist = distance_matrix.copy()
    rows, cols = dist.shape
    
    # Mask for available rows and cols
    row_available = np.ones(rows, dtype=bool)
    col_available = np.ones(cols, dtype=bool)
    
    # Flatten and sort indices by distance (ascending)
    # We want smallest distance (highest IoU)
    flat_indices = np.argsort(dist.ravel())
    
    for idx in flat_indices:
        r, c = divmod(idx, cols)
        
        if row_available[r] and col_available[c]:
            if dist[r, c] > thresh:
                # Since it's sorted, all subsequent will be > thresh
                break
                
            matched_indices.append((r, c))
            row_available[r] = False
            col_available[c] = False
            
    unmatched_rows = np.where(row_available)[0].tolist()
    unmatched_cols = np.where(col_available)[0].tolist()
    
    return matched_indices, unmatched_rows, unmatched_cols


class TrackerNode(BaseNode):
    """
    Tracker Node that implements ByteTrack algorithm to track objects across frames.
    Takes detections as input and outputs tracks with IDs.
    """
    info = str(_info)
    display_name = 'Tracker'
    icon = '👣'
    category = 'vision'
    color = '#2C3E50'
    border_color = '#1A252F'
    text_color = '#ECF0F1'
    
    DEFAULT_CONFIG = {
        'track_thresh': '0.5',
        'track_buffer': '30',
        'match_thresh': '0.8',
        'draw_tracks': 'true'
    }
    
    properties = [
        {
            'name': 'track_thresh',
            'label': 'Tracking Threshold',
            'type': 'text',
            'placeholder': '0.5'
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
    
    def __init__(self, node_id=None, name="tracker"):
        self.tracker = None
        self.last_config = {}
        super().__init__(node_id, name)
        
    def _init_tracker(self):
        track_thresh = self.get_config_float('track_thresh', 0.5)
        track_buffer = self.get_config_int('track_buffer', 30)
        match_thresh = self.get_config_float('match_thresh', 0.8)
        
        self.tracker = ByteTracker(
            track_thresh=track_thresh,
            track_buffer=track_buffer,
            match_thresh=match_thresh
        )
        
        self.last_config = {
            'track_thresh': track_thresh,
            'track_buffer': track_buffer,
            'match_thresh': match_thresh
        }
        
    def configure(self, config):
        super().configure(config)
        
        # Check if tracker params changed
        track_thresh = self.get_config_float('track_thresh', 0.5)
        track_buffer = self.get_config_int('track_buffer', 30)
        match_thresh = self.get_config_float('match_thresh', 0.8)
        
        if (track_thresh != self.last_config.get('track_thresh') or
            track_buffer != self.last_config.get('track_buffer') or
            match_thresh != self.last_config.get('match_thresh')):
            self._init_tracker()
            
    def on_input(self, msg, input_index=0):
        try:
            payload = msg.get('payload', {})
            if not isinstance(payload, dict):
                self.send(msg)
                return
                
            detections = payload.get('detections', [])
            if detections is None:
                detections = []
            
            # Prepare detections for tracker: [x1, y1, x2, y2, score, class_id]
            tracker_inputs = []
            for det in detections:
                bbox = det.get('bbox', [])
                if len(bbox) == 4:
                    score = det.get('confidence', 0.0)
                    class_id = det.get('class_id', 0)
                    tracker_inputs.append(bbox + [score, class_id])
                    
            # Run tracker
            if self.tracker is None:
                self._init_tracker()
                
            online_targets = self.tracker.update(tracker_inputs)
            
            # Format output tracks
            tracks = []
            for t in online_targets:
                tlwh = t.tlwh
                tid = t.track_id
                vertical = tlwh[2] / tlwh[3] > 1.6
                if tlwh[2] * tlwh[3] > 10 and not vertical:
                    tracks.append({
                        'track_id': int(tid),
                        'class_id': int(t.class_id),
                        'confidence': float(t.score),
                        'bbox': [float(tlwh[0]), float(tlwh[1]), float(tlwh[0] + tlwh[2]), float(tlwh[1] + tlwh[3])], # x1, y1, x2, y2
                        'bbox_wh': [float(tlwh[0]), float(tlwh[1]), float(tlwh[2]), float(tlwh[3])] # x, y, w, h
                    })
                    
            # Update payload
            payload['tracks'] = tracks
            payload['track_count'] = len(tracks)
            
            # Draw tracks if requested
            if self.get_config_bool('draw_tracks', True) and 'image' in payload:
                try:
                    import cv2
                    image, fmt = self.decode_image(payload['image'])
                    if image is not None and fmt is not None:
                        for t in tracks:
                            bbox = [int(x) for x in t['bbox']]
                            tid = t['track_id']
                            cls_id = t['class_id']
                            
                            # Draw box
                            cv2.rectangle(image, (bbox[0], bbox[1]), (bbox[2], bbox[3]), (0, 255, 0), 2)
                            
                            # Draw label
                            label = f"ID:{tid} C:{cls_id}"
                            cv2.putText(image, label, (bbox[0], bbox[1] - 10), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                                    
                        # Encode back
                        encoded = self.encode_image(image, fmt)
                        if encoded:
                            payload['image'] = encoded
                except Exception as e:
                    self.report_error(f"Error drawing tracks: {e}")
                    
            self.send(msg)
            
        except Exception as e:
            logger.error(f"Error in TrackerNode: {e}", exc_info=True)
            self.report_error(f"Tracker error: {e}")
            # Pass through message even on error
            self.send(msg)
