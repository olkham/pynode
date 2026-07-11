"""File upload API."""

import os

from flask import Blueprint, jsonify, request

from pynode.api.helpers import _get_manager

uploads_bp = Blueprint('uploads', __name__)

# File upload configuration: uploads may only land in these subdirectories
# of the manager's upload_base_dir. Anything else is rejected.
ALLOWED_UPLOAD_SUBDIRS = ('models', 'uploads')


@uploads_bp.route('/api/upload/file', methods=['POST'])
def upload_file():
    """Upload a file (model, video, etc.) and save to the server."""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400

        file = request.files['file']
        if not file.filename or file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400

        # Determine upload directory from optional 'directory' field, default to models.
        # Only allowlisted subdirectory names are accepted (no separators, no
        # traversal) and the resolved path must stay inside the upload base dir.
        upload_subdir = request.form.get('directory', 'models')
        normalized_subdir = os.path.normpath(upload_subdir).replace('\\', '/')
        if normalized_subdir not in ALLOWED_UPLOAD_SUBDIRS:
            return jsonify({
                'success': False,
                'error': f"Invalid upload directory. Allowed: {', '.join(ALLOWED_UPLOAD_SUBDIRS)}"
            }), 400

        base_dir = os.path.realpath(_get_manager().upload_base_dir)
        upload_dir = os.path.realpath(os.path.join(base_dir, normalized_subdir))
        if upload_dir != base_dir and not upload_dir.startswith(base_dir + os.sep):
            return jsonify({
                'success': False,
                'error': 'Invalid upload directory: outside allowed base'
            }), 400
        os.makedirs(upload_dir, exist_ok=True)

        # Save the file
        filename = os.path.basename(file.filename)
        file_path = os.path.join(upload_dir, filename)
        file.save(file_path)

        return jsonify({
            'success': True,
            'model_path': file_path,
            'file_path': file_path,
            'filename': filename
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
