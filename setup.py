from setuptools import setup, find_packages

with open('requirements.txt') as fp:
    install_requires = fp.read()

setup(
    name='video-annotation-tool',
    version='0.5.0',
    description='Vibronav video annotation tool',
    author='Hamza Oran',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3'
    ],
    packages=find_packages(),
    install_requires=install_requires,
    extras_require={},
    data_files=[],
    entry_points={
        'console_scripts': ['video_annotation_tool=video_annotation_tool.video_annotation_tool:main'],
    }
)
