import cv2
import argparse
import json
import os
import subprocess
from scipy.io import wavfile
from matplotlib.backends.backend_agg import FigureCanvasAgg
import matplotlib.pyplot as plt
import numpy as np
import cv2
import pandas as pd

def read_wave(path):
    sample_rate, x = wavfile.read(path)
    x = x.T
    if x.dtype == np.int32:
        x = x / float(2**31-1)
    elif x.dtype == np.int16:
        x = x / float(2**15-1)
    if len(x.shape) == 1:
        x = x[None, :]
    return sample_rate, x

def build_waveform_image(audio_signal, sr, width, height, audio_channel, bg=(24, 24, 24), fg=(230, 230, 230)):

    audio_signal = audio_signal[audio_channel, :]

    img = np.full((height, width, 3), bg, dtype=np.uint8)

    samples_per_col = int(np.ceil(audio_signal.shape[0] / width))
    mid_y = height // 2
    cv2.line(img, (0, mid_y), (width - 1, mid_y), (100, 100, 100), 1)

    for x in range(width):
        s = x * samples_per_col
        e = min((x + 1) * samples_per_col, audio_signal.shape[0])
        if s >= e:
            break

        seg = audio_signal[s:e]
        min_val = np.min(seg)
        max_val = np.max(seg)

        y_min = int((1 - max_val) * 0.5 * (height - 1))
        y_max = int((1 - min_val) * 0.5 * (height - 1))
        cv2.line(img, (x, y_min), (x, y_max), fg, 1)

    return img

def draw_playhead(img, position, max_position):
    h, w = img.shape[:2]
    
    position = float(position)
    x = int((position / float(max_position)) * (w - 1))
    x = max(0, min(w - 1, x))
    cv2.line(img, (x, 0), (x, h - 1), (0, 180, 255), 1)
    return img


def build_velocity_image(labelled_positions_path, width, height, bg=(255, 255, 255), line=(255, 0, 0), axis=(200, 200, 200)):
    img = np.full((height, width, 3), bg, dtype=np.uint8)

    if not labelled_positions_path or not os.path.exists(labelled_positions_path):
        cv2.putText(img, 'No velocity data', (10, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return img
    
    df = pd.read_csv(labelled_positions_path)

    velocity_original = df['velocity'].copy()
    df['velocity'] = df['velocity'].rolling(window=3, center=True).mean()
    df['velocity'] = df['velocity'].fillna(velocity_original)

    frames = df['Frame'].to_numpy(dtype=np.int64)
    velocities = df['velocity'].fillna(0).to_numpy(dtype=np.float32)

    vmax = float(np.nanmax(np.abs(velocities)))
    v_norm = np.clip(velocities / vmax, -1.0, 1.0)

    total_frames = frames.shape[0]
    pts = []
    for frame, val in zip(frames, v_norm):
        x = int((frame - 1) * (width - 1) / max(1, total_frames - 1))
        y = int((1 - (val + 1) / 2) * (height - 1))
        pts.append((x, y))

    cv2.line(img, (0, height // 2), (width - 1, height // 2), axis, 1)

    cv2.polylines(img, [np.array(pts, dtype=np.int32)], False, line, 1)

    return img

def durations_match(total_frames, audio_sr, audio_signal, eps=0.1):

    video_duration = total_frames / 30.0
    audio_duration = audio_signal.shape[1] / audio_sr
    print(abs(video_duration - audio_duration))

    return abs(video_duration - audio_duration) < eps

def convert_video_to_h264(input_path):
    
    command_check = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name",
        "-of", "default=noprint_wrappers=1:nokey=1",
        input_path
    ]
    result = subprocess.run(command_check, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    codec = result.stdout.decode().strip()
    
    if codec == "h264":
        print(f"{input_path} is already H.264, skipping conversion.")
        return input_path


    temp_output = input_path + "_tmp.mp4"
    command_convert = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-c:v", "libx264", "-preset", "slow", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        temp_output
    ]
    print(f"Converting: {input_path} → H.264")
    result = subprocess.run(command_convert, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if os.path.exists(temp_output):
        os.replace(temp_output, input_path)
        print(f"Conversion done: {input_path}")
        return input_path
    else:
        print(f"Error converting {input_path}:\n{result.stderr.decode()}")
        return input_path

    
def get_json_filename(video_filename):
    base_name = os.path.splitext(video_filename)[0]
    base_name_lower = base_name.lower()

    if "cam1" in base_name_lower:
        base_name = base_name_lower.replace("cam1", "")
    elif "cam2" in base_name_lower:
        base_name = base_name_lower.replace("cam2", "")

    base_name = base_name.strip(" _-")
    return base_name + ".json"

def merge_annotations(video_path, new_annotations, should_update_audio):
    original_video_file = os.path.basename(video_path)
    json_filename = get_json_filename(original_video_file)
    json_path = os.path.join(os.path.dirname(video_path), json_filename)

    existing_data = {}
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)

    existing_data["video_file"] = original_video_file
    if "video_annotations" not in existing_data:
        existing_data["video_annotations"] = {}
    if "audio_annotations" not in existing_data and should_update_audio:
        existing_data["audio_annotations"] = {}

    for k, v in new_annotations.items():
        if v["frame"] is None or v["time"] is None:
            if k in existing_data["video_annotations"]:
                del existing_data["video_annotations"][k]
        if v["sample"] is None and should_update_audio:
            if k in existing_data["audio_annotations"]:
                del existing_data["audio_annotations"][k]

        if v["frame"] is not None and v["time"] is not None:
            existing_data["video_annotations"][k] = {"time": v["time"], "frame": v["frame"]}

        if v['sample'] is not None and should_update_audio:
            existing_data["audio_annotations"][k] = {"time": v["time"], "sample": int(v["sample"])}


    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=4)
        print(f"Annotations for {video_path} updated in {json_path}.")

def update_annotations(annotations, *frames_times):
    for i, (frame, time, sample_rate) in enumerate(frames_times, start=1):
        annotations[str(i)] = {"frame": frame, "time": time, "sample": time * sample_rate}

zoom_level = 1.0
zoom_center = None
last_frame = None

def get_zoomed_frame(window_name, frame, zoom_level, center=None):
    h, w = frame.shape[:2]

    if zoom_level <= 1.0:
        return frame

    new_w = int(w / zoom_level)
    new_h = int(h / zoom_level)

    if center is None:
        center_x, center_y = w // 2, h // 2
    else:
        center_x, center_y = center

    x1 = max(center_x - new_w // 2, 0)
    y1 = max(center_y - new_h // 2, 0)
    x2 = min(x1 + new_w, w)
    y2 = min(y1 + new_h, h)

    cropped = frame[y1:y2, x1:x2]
    zoomed_frame = cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)

    return zoomed_frame

def mouse_callback(event, x, y, flags, param):
    global zoom_level, zoom_center, last_frame

    if event == cv2.EVENT_MOUSEWHEEL:
        if flags > 0:  # Scroll up
            zoom_level = min(zoom_level + 0.2, 5.0)
        else:  # Scroll down
            zoom_level = max(zoom_level - 0.2, 1.0)
        zoom_center = (x, y)

        if last_frame is not None:
            get_zoomed_frame('Video Annotation', last_frame, zoom_level, zoom_center)

def annotate_video(video_path, audio_path, labelled_position_path, audio_channel):
    global zoom_level, zoom_center, last_frame
    mp4_path = convert_video_to_h264(video_path)
    cap = cv2.VideoCapture(mp4_path)

    if not cap.isOpened():
        print("Error: Could not open video.")
        return
    
    audio_sr = None
    audio_data = None
    audio_duration = 0.0

    if audio_path and os.path.exists(audio_path):
        try:
            audio_sr, audio_signal = read_wave(audio_path)
            audio_data = audio_signal
            audio_duration = audio_signal.shape[1] / audio_sr
        except Exception as e:
            print(f"Error reading audio file {audio_path}: {e}")

    cv2.namedWindow('Video Annotation')
    cv2.setMouseCallback('Video Annotation', mouse_callback)

    annotations = {}
    e1_frame = e2_frame = e3_frame = e4_frame = None
    paused = False
    frame_buffer = []
    key_pressed = None
    quit_app = False

    json_filename = get_json_filename(os.path.basename(video_path))
    json_path = os.path.join(os.path.dirname(video_path), json_filename)
    existing_annotations_title = ""
    existing_annotations = {}

    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
            if "video_annotations" in existing_data:
                existing_annotations = existing_data["video_annotations"]
                existing_annotations_title = " | Existing :"
                for key, value in existing_annotations.items():
                    frame = value.get("frame")
                    time = value.get("time")
                    if frame is not None and time is not None:
                        existing_annotations_title += f" {key}: F(T): {frame}({time:.2f}s)"

    ret, frame = cap.read()
    if not ret:
        print("Error: Could not read the first frame.")
        cap.release()
        return
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    last_frame = frame.copy()
    vh, vw = frame.shape[:2]
    waveform_h = 140
    velocity_h = 140

    base_waveform = build_waveform_image(audio_data, audio_sr, vw, waveform_h, audio_channel)
    velocity_plot = build_velocity_image(labelled_position_path, vw, velocity_h)

    while True:
        if not paused:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            last_frame = frame.copy()
            frame_buffer.append(frame)

        frame_index = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        time_in_seconds = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

        display_frame = get_zoomed_frame('Video Annotation', frame, zoom_level, zoom_center)

        wf = base_waveform.copy()
        draw_playhead(wf, time_in_seconds, audio_duration)
        vel = velocity_plot.copy()
        draw_playhead(vel, frame_index - 1, total_frames - 1)

        if display_frame.shape[1] != wf.shape[1]:
            wf = cv2.resize(wf, (display_frame.shape[1], wf.shape[0]))
        
        combined = np.vstack([display_frame, wf, vel])

        title_text = f'{os.path.basename(video_path)} | {frame_index}({time_in_seconds:.2f}s){existing_annotations_title}'
        if e1_frame is not None:
            title_text += f' | New : E1 F(T): {e1_frame}({e1_time:.2f}s)'
        if e2_frame is not None and e1_frame is not None and e1_frame<e2_frame:
            title_text += f' | E2 F(T): {e2_frame}({e2_time:.2f}s)'
        if e3_frame is not None and e2_frame is not None and e2_frame<=e3_frame and e1_frame<e2_frame:
            title_text += f' | E3 F(T): {e3_frame}({e3_time:.2f}s)'
        if e4_frame is not None and e3_frame is not None and e3_frame<=e4_frame and e2_frame<=e3_frame:
            title_text += f' | E4 F(T): {e4_frame}({e4_time:.2f}s)'

        cv2.setWindowTitle('Video Annotation', title_text)
        cv2.imshow('Video Annotation', combined)
        key = cv2.waitKey(33)

        if key == 27:  # ESC
            quit_app = True
            break
        elif key == 32:  # Space pause/play
            paused = not paused
        elif key == ord('r'):  # Reset zoom
            zoom_level = 1.0
            zoom_center = None
        elif key == ord('1'):
            e1_frame = frame_index; e1_time = time_in_seconds
            if e2_frame is not None and e1_frame > e2_frame:
                e2_frame = e3_frame = e4_frame = None
        elif key == ord('2') and e1_frame is not None:
            e2_frame = frame_index; e2_time = time_in_seconds
            if e2_frame < e1_frame:
                e2_frame = e3_frame = e4_frame = None
        elif key == ord('3') and e2_frame is not None:
            e3_frame = frame_index; e3_time = time_in_seconds
            if e3_frame < e2_frame:
                e3_frame = None
        elif key == ord('4') and e3_frame is not None:
            e4_frame = frame_index; e4_time = time_in_seconds
            if e4_frame < e3_frame:
                e4_frame = None
            update_annotations(annotations, (e1_frame, e1_time, audio_sr), (e2_frame, e2_time, audio_sr), (e3_frame, e3_time, audio_sr), (e4_frame, e4_time, audio_sr))
        elif key == ord('5') and "1" in existing_annotations:
            e1_frame = existing_annotations["1"]["frame"]; e1_time = existing_annotations["1"]["time"]
        elif key == ord('6') and "2" in existing_annotations:
            e2_frame = existing_annotations["2"]["frame"]; e2_time = existing_annotations["2"]["time"]
        elif key == ord('7') and "3" in existing_annotations:
            e3_frame = existing_annotations["3"]["frame"]; e3_time = existing_annotations["3"]["time"]
        elif key == ord('8') and "4" in existing_annotations:
            e4_frame = existing_annotations["4"]["frame"]; e4_time = existing_annotations["4"]["time"]
            update_annotations(annotations, (e1_frame, e1_time, audio_sr), (e2_frame, e2_time, audio_sr), (e3_frame, e3_time, audio_sr), (e4_frame, e4_time, audio_sr))
        elif key == ord('n'):
            break
        elif key == ord('c'):
            e1_frame = e2_frame = e3_frame = e4_frame = None
            e1_time = e2_time = e3_time = e4_time = None
            update_annotations(annotations, (e1_frame, e1_time, audio_sr), (e2_frame, e2_time, audio_sr), (e3_frame, e3_time, audio_sr), (e4_frame, e4_time, audio_sr))

        if key == ord('a'): key_pressed = 'a'
        elif key == ord('d'): key_pressed = 'd'
        elif key == -1: key_pressed = None

        if key_pressed == 'a' and paused:
            if len(frame_buffer) > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, cap.get(cv2.CAP_PROP_POS_FRAMES) - 2)
                ret, frame = cap.read()
                if ret:
                    last_frame = frame.copy()
                    frame_buffer.pop()
        elif key_pressed == 'd' and paused:
            ret, frame = cap.read()
            if ret:
                last_frame = frame.copy()
                frame_buffer.append(frame)

    cap.release()
    cv2.destroyAllWindows()

    if annotations:
        should_update_audio = durations_match(total_frames, audio_sr, audio_data)
        merge_annotations(video_path, annotations, should_update_audio)
    else:
        print(f"No annotations made for {video_path}.")

    if mp4_path != video_path:
        os.remove(mp4_path)

    return quit_app


def process_videos_in_folder(video_path, audio_path, labelled_position_path, audio_channel):

    videos = [f for f in os.listdir(video_path) if f.lower().endswith(('.mp4', '.webm'))]

    for video_file in videos:
        file_basename, ext = os.path.splitext(video_file)
        video_path = os.path.join(video_path, file_basename + ext)
        audio_path = os.path.join(audio_path, file_basename + '.wav')
        labelled_position_path = os.path.join(labelled_position_path, file_basename + '.csv')
        quit_app = annotate_video(video_path, audio_path, labelled_position_path, audio_channel)
        if quit_app:
            break

def parse_args():
    parser = argparse.ArgumentParser(description='Annotate time instants in videos in a folder.')
    parser.add_argument('--video-path', type=str, help='Path to the folder containing video files')
    parser.add_argument('--audio-path', type=str, help='Path to the folder containing audio files')
    parser.add_argument('--velocity-path', type=str, help='Path to the folder containing velocity files')
    parser.add_argument('--audio-channel', type=int, default=0, help='Audio channel to use for waveform (default: 0)')
    return parser.parse_args()

def main():

    args = parse_args()

    video_path = args.video_path
    audio_path = args.audio_path
    labelled_position_path = args.velocity_path
    audio_channel = args.audio_channel

    process_videos_in_folder(video_path, audio_path, labelled_position_path, audio_channel)

if __name__ == "__main__":
    main()