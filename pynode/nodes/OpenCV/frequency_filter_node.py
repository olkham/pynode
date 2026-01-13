"""
OpenCV Frequency Filter Node - filters frequencies and performs inverse FFT.
"""

import cv2
import numpy as np
from typing import Any, Dict
from pynode.nodes.base_node import BaseNode, Info, MessageKeys

_info = Info()
_info.add_text("Modifies frequency components (filtering) and reconstructs the image via Inverse FFT.")
_info.add_header("Inputs")
_info.add_bullet("Input 0:", "FFT Node output (must contain frequency data)")
_info.add_header("Outputs")
_info.add_bullet("Output 0:", "Filtered Image (spatial domain) or Filtered Spectrum")
_info.add_header("Operations")
_info.add_bullets(
    ("Low Pass:", "Keeps low frequencies (center), suppresses details/noise. Blurs the image."),
    ("High Pass:", "Keeps high frequencies (edges), suppresses smooth areas. Edge detection."),
    ("Notch Filter:", "Manually blocks specific frequency spots (harmonics/noise) using coordinates.")
)
_info.add_header("Notch Configuration")
_info.add_text("Enter coordinates to block in the 'Notch Filters' field. Format: x,y,radius; x2,y2,radius2.")
_info.add_text("Example: '100,200,5; 340,150,10' blocks two circular regions.")


class FrequencyFilterNode(BaseNode):
    """
    Frequency Filter Node - applies masks to frequency domain data.
    """
    info = str(_info)
    display_name = 'Freq Filter'
    icon = '⌖'
    category = 'opencv'
    color = '#8E44AD'  # Same purple scheme
    border_color = '#6C3483'
    text_color = '#FFFFFF'
    input_count = 1
    output_count = 1
    
    DEFAULT_CONFIG = {
        'filter_type': 'low_pass',
        'radius': 30,
        'notch_filters': '',
        'symmetric_notches': 'true',
        'output_mode': 'reconstructed'
    }
    
    properties = [
        {
            'name': 'filter_type',
            'label': 'Filter Type',
            'type': 'select',
            'options': [
                {'value': 'low_pass', 'label': 'Low Pass (Blur)'},
                {'value': 'high_pass', 'label': 'High Pass (Edges)'},
                {'value': 'none', 'label': 'None (Pass Through / Just Notches)'}
            ],
            'default': DEFAULT_CONFIG['filter_type']
        },
        {
            'name': 'radius',
            'label': 'Cutoff Radius',
            'type': 'number',
            'default': DEFAULT_CONFIG['radius'],
            'min': 1,
            'max': 500
        },
        {
            'name': 'notch_filters',
            'label': 'Notch Filters (x,y,r; ...)',
            'type': 'text',
            'default': DEFAULT_CONFIG['notch_filters'],
            'help': 'Block specific frequencies. Format: x,y,radius (semicolon separated). E.g. 120,45,5'
        },
        {
            'name': 'symmetric_notches',
            'label': 'Apply Symmetrically',
            'type': 'checkbox',
            'default': DEFAULT_CONFIG['symmetric_notches'],
            'help': 'Automatically block the symmetric point across the center (required for real signals)'
        },
        {
            'name': 'output_mode',
            'label': 'Output Mode',
            'type': 'select',
            'options': [
                {'value': 'reconstructed', 'label': 'Reconstructed Image'},
                {'value': 'spectrum', 'label': 'Filtered Spectrum (View)'},
                {'value': 'both', 'label': 'Both (Reconstructed + Spectrum)'}
            ],
            'default': DEFAULT_CONFIG['output_mode'],
            'help': 'View the resulting image or the modified frequency spectrum'
        }
    ]
    
    def on_input(self, msg: Dict[str, Any], input_index: int = 0):
        """Process incoming frequency data."""
        # Check for FFT data
        dft_shift = msg.get('_fft_data')
        
        if dft_shift is None:
            # If no FFT data, try to look for image in payload to auto-convert (optional convenience)
            # But strictly, we should expect FFT data.
            # Let's pass through if we can't process
            self.send(msg)
            return
            
        rows, cols = dft_shift.shape[:2]
        crow, ccol = rows//2, cols//2  # Center
        
        # Create a mask, first separate channels (2 channels: Real, Imag)
        # We need a mask that applies to both channels
        mask = np.zeros((rows, cols, 2), np.uint8)
        
        try:
            radius = int(self.config.get('radius', 30))
        except ValueError:
            radius = 30
            
        filter_type = self.config.get('filter_type', 'low_pass')
        
        # Create circular mask area
        # Using grid indices
        y, x = np.ogrid[:rows, :cols]
        mask_area = (x - ccol)**2 + (y - crow)**2 <= radius*radius
        
        if filter_type == 'low_pass':
            # 1 inside circle, 0 outside
            mask[mask_area] = 1
        elif filter_type == 'high_pass':
            # 0 inside circle, 1 outside
            mask[~mask_area] = 1
        else: # none / pass-through
            mask.fill(1)
            
        # Apply Notch Filters (Manual Blocking)
        notch_str = self.config.get('notch_filters', '')
        symmetric = self.config.get('symmetric_notches', 'true') == 'true'
        
        if notch_str:
            try:
                for notch_def in notch_str.split(';'):
                    if not notch_def.strip():
                        continue
                    
                    parts = [float(p.strip()) for p in notch_def.split(',') if p.strip()]
                    if len(parts) >= 2:
                        nx, ny = int(parts[0]), int(parts[1])
                        # Default radius 5 if not specified
                        nr = int(parts[2]) if len(parts) > 2 else 5
                        
                        # Apply notch at (nx, ny)
                        # Remember x matches cols index, y matches rows index
                        notch_area = (x - nx)**2 + (y - ny)**2 <= nr*nr
                        mask[notch_area] = 0
                        
                        if symmetric:
                            # Calculate symmetric point relative to center (ccol, crow)
                            # Actually relative to image dimensions: (cols - x, rows - y)
                            # Center is at axis of rotation
                            # Point (x, y) reflected across (cx, cy) is (2cx - x, 2cy - y)
                            # Since cx=cols/2, 2cx = cols. So (cols - x, rows - y) approximately
                            # Let's use exact center calculation
                            
                            # Center of image is (cols/2, rows/2).
                            # Because indices are 0-based, exact center is (cols-1)/2 ?? 
                            # FFT shift puts DC at rows//2, cols//2.
                            
                            sym_x = 2 * ccol - nx
                            sym_y = 2 * crow - ny
                            
                            # Ensure within bounds
                            # if 0 <= sym_x < cols and 0 <= sym_y < rows:
                            # Actually, simpler logic:
                            # The mask uses coordinates. Creating a circular mask at sym coords works.
                            
                            notch_area_sym = (x - sym_x)**2 + (y - sym_y)**2 <= nr*nr
                            mask[notch_area_sym] = 0
                            
            except Exception as e:
                # Log error but continue with what we have
                print(f"Error parsing notch filters: {e}")
            
        # Apply mask
        fshift = dft_shift * mask
        
        result_img = None
        spectrum_img = None
        output_mode = self.config.get('output_mode', 'reconstructed')
        
        def compute_spectrum(f_data):
            mag = cv2.magnitude(f_data[:,:,0], f_data[:,:,1])
            mag_spec = 20 * np.log(mag + 1)
            cv2.normalize(mag_spec, mag_spec, 0, 255, cv2.NORM_MINMAX)
            return np.uint8(mag_spec)

        def compute_reconstruction(f_data):
            f_ishift = np.fft.ifftshift(f_data)
            img_b = cv2.idft(f_ishift)
            img_b = cv2.magnitude(img_b[:,:,0], img_b[:,:,1])
            cv2.normalize(img_b, img_b, 0, 255, cv2.NORM_MINMAX)
            return np.uint8(img_b)
            
        if output_mode == 'spectrum':
            result_img = compute_spectrum(fshift)
        elif output_mode == 'both':
            result_img = compute_reconstruction(fshift)
            spectrum_img = compute_spectrum(fshift)
        else:
            result_img = compute_reconstruction(fshift)
        
        # Create response
        new_msg = msg.copy()
        
        # Update payload
        # Use existing format type or default to jpg
        # We can extract format from payload path if present, or just assume
        # The encode_image method usually handles basic types.
        
        # We need to construct a proper payload structure if it doesn't exist
        if MessageKeys.PAYLOAD not in new_msg or not isinstance(new_msg[MessageKeys.PAYLOAD], dict):
             new_msg[MessageKeys.PAYLOAD] = {}
             
        # Encode
        # Use bgr_numpy_dict to provide a consistent object structure (data, width, height, etc)
        # while keeping the data as numpy array for efficiency.
        format_type = 'bgr_numpy_dict'
        new_msg[MessageKeys.PAYLOAD][MessageKeys.IMAGE.PATH] = self.encode_image(result_img, format_type)
        
        if spectrum_img is not None:
             new_msg[MessageKeys.PAYLOAD]['spectrum'] = self.encode_image(spectrum_img, format_type)
        
        # Update metadata for chaining (optional)
        new_msg['_fft_data'] = fshift
        
        self.send(new_msg)
