# Video Annotation Tool

## Tool Description
This tool developed for annotating important events and phases during measurements. 
![image](https://github.com/OranHamza/video_annotation_tool/assets/127665894/d607e94e-4445-4b22-989f-3a807da1af1b)

**Important events**: 
- The puncture moments into gelatine (E1),
- From gelatine into the tissue (E2), 
- From tissue into gelatine (E3), 
- The moment when the needle stops moving and start being pulled out of the phantom (E4).

**Important phases**: 
- When the needle passes through gelatine (P1), 
- When it passes through the tissue (P2), 
- When it passes through gelatine again after exiting the tissue (P3).

## Installation

### Tool installation

Execute in CLI:

```python -m pip install https://github.com/Vibronav/video_annotation_tool/archive/master.zip```

### Setting up FFmpeg(For Windows)

1. **Download FFmpeg**: [Download FFmpeg](https://drive.google.com/drive/folders/1_xW8WYHzj_xRmdIu2VqPdSPr1Pb3jqtQ?usp=sharing) from the provided link.
2. **Extract Files**: Extract the downloaded zip file to your computer.
3. **Copy Folder**: Locate the extracted folder and copy it.
4. **Paste to C Drive**: Navigate to your **"C:"** drive and paste the copied folder there.
5. **Set Path**: Open **"Control Panel"** -> **"System"** -> **"Advanced system settings"** -> **"Environment Variables"**
   - In the **User Variables** area, identify and select **Path** and then proceed to hit the **Edit** option.
    ![image](https://github.com/OranHamza/video_annotation_tool/assets/127665894/8bcde9f4-acee-41f5-9198-275cae2a6caf)
   - Select **New** in the following dialog box.
     ![image](https://github.com/OranHamza/video_annotation_tool/assets/127665894/1dffbf72-6363-4ca6-b9b4-35dd3cc0f995)
   - Enter **C:\ffmpeg\bin** in the provided space and select **OK** to confirm. This path indicates that the FFmpeg files are located at C:\. If FFmpeg files are located at a different location on your system, make sure that this path contains the correct location.
     ![image](https://github.com/OranHamza/video_annotation_tool/assets/127665894/d0f1bbad-a58c-4c52-b6b0-97c145e92a7e)

7. **Confirm Changes**: The final step is to verify that the FFmpeg is properly installed and available for use.
Start by launching the Command Prompt or PowerShell and enter **ffmpeg**.

If the installation is successful, you will see something like the following:
![image](https://github.com/OranHamza/video_annotation_tool/assets/127665894/e288813e-d773-4e91-8c1b-87da5153d781)

## Usage

1. **Run Code**: Execute the code using the command line interface (CLI).

```
usage: video_annotation_tool.py [-h] [--video-path VIDEO_PATH] [--audio-path AUDIO_PATH] [--velocity-path VELOCITY_PATH] [--audio-channel AUDIO_CHANNEL]                                                                   

Annotate time instants in videos in a folder.

options:
  -h, --help            show this help message and exit
  --video-path VIDEO_PATH
                        Path to the folder containing video files
  --audio-path AUDIO_PATH
                        Path to the folder containing audio files
  --velocity-path VELOCITY_PATH
                        Path to the folder containing velocity files
  --audio-channel AUDIO_CHANNEL
                        Audio channel to use for waveform (default: 0)
```

OR(run this command in the commond line from the folder where your 'video_annotation_tool.py' script is located.)

```python video_annotation_tool.py "your videos folder path"```

2. **Controls**:
- Press the **'Space'** key to toggle between pause and play.
- Press **'1'** to mark the event E1.
- Press **'2'** to mark the event E2.
- Press **'3'** to mark the event E3.
- Press **'4'** to mark the event E4.
- Press **'5'** to mark the event E5.
- Press **'6'** to mark the event E6.
- Press **'7'** to mark the event E7.
- Press **'8'** to mark the event E8.
- Press **'crtl + 1-8'** to use the exist event E1-E8 as new E1-E8
- Press **'c'** to clear all annotations.
- Use **'a'** and **'d'** to navigate backward and forward in the video when paused.
- Press **'n'** to move to the next video.
- Press **'esc'** to close the tool.

3. **Saving Annotations**: Annotations are automatically saved to a JSON file after the user exits the annotation process. It will be saved to sepatare folder 'annotations' in the same location as folder with videos

## Interface

1. **Windows Title**: In the opened video window title, you will see the current video name, frame and seconds, along with annotations from the previous video if available. Additionally, any new video annotations, if added, will be visible.Existing belongs to the previous annotations. New for the new annotations."F" corresponds Frame ,"T" corresponds Time.

![image](https://github.com/OranHamza/video_annotation_tool/assets/127665894/d157ab45-d45c-4261-a52f-cc72019ff558)




