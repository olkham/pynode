"""
PyNode - A Node-RED-like Visual Workflow System with Python Backend
"""

from setuptools import setup, find_packages
import os

# Read requirements from requirements.txt
def read_requirements():
    req_file = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    with open(req_file, 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

# Read long description from README
def read_long_description():
    readme_file = os.path.join(os.path.dirname(__file__), 'README.md')
    if os.path.exists(readme_file):
        with open(readme_file, 'r', encoding='utf-8') as f:
            return f.read()
    return ''

setup(
    name='pynode',
    version='0.1.0',
    description='A Node-RED-like visual workflow system with Python backend',
    long_description=read_long_description(),
    long_description_content_type='text/markdown',
    author='PyNode Team',
    url='https://github.com/yourusername/pynode',
    packages=find_packages(),
    include_package_data=True,
    install_requires=read_requirements(),
    entry_points={
        'console_scripts': [
            'pynode=pynode.main:main',
        ],
    },
    python_requires='>=3.8',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
    package_data={
        'pynode': [
            'static/**/*',
            'nodes/**/*',
        ],
    },
)
