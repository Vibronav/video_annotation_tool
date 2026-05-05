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
from pynput import keyboard
from video_annotation_tool.audio_player import AudioPlayer

WINDOW_NAME = 'Video Annotation'
MAX_WINDOW_WIDTH = 1600
MAX_WINDOW_HEIGHT = 1200
WINDOW_HORIZONTAL_MARGIN = 40
WINDOW_VERTICAL_MARGIN = 80
WINDOW_CHROME_HEIGHT_ALLOWANCE = 100
MAX_CONTENT_HEIGHT_SCREEN_FRACTION = 0.75
CONTROL_BAR_HEIGHT = 48
DEFAULT_PLOT_HEIGHT = 140
MIN_PLOT_HEIGHT = 48

ctrl_pressed = False
event_key = None
show_mode = 1 # 0=waveform, 1=spectrogram
playback_speed = 100

def _on_mode_change(key):
    global show_mode
    show_mode = int(key)

def _on_press(key):
    try:
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            global ctrl_pressed
            ctrl_pressed = True
        else:
            global event_key
            if hasattr(key, 'char') and key.char is not None:
                event_key = key.char
            elif hasattr(key, 'vk'):
                event_key = chr(key.vk)
    except Exception as e:
        print(f"Error in key press: {e}")

def _on_release(key):
    try:
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            global ctrl_pressed
            ctrl_pressed = False
        else:
            global event_key
            event_key = None
    except Exception as e:
        print(f"Error in key release: {e}")

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

def get_screen_size(default=(1280, 720)):
    try:
        if os.name == 'nt':
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()

            class RECT(ctypes.Structure):
                _fields_ = [
                    ('left', ctypes.c_long),
                    ('top', ctypes.c_long),
                    ('right', ctypes.c_long),
                    ('bottom', ctypes.c_long),
                ]

            rect = RECT()
            SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                return rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        pass

    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        screen_size = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        return screen_size
    except Exception:
        return default

def calculate_display_layout(video_width, video_height):
    screen_w, screen_h = get_screen_size()
    available_w = max(1, screen_w - 2 * WINDOW_HORIZONTAL_MARGIN)
    available_h = max(1, screen_h - 2 * WINDOW_VERTICAL_MARGIN)
    max_content_w = min(MAX_WINDOW_WIDTH, available_w)
    max_window_h = min(MAX_WINDOW_HEIGHT, available_h)
    max_content_h = min(
        max(1, max_window_h - WINDOW_CHROME_HEIGHT_ALLOWANCE),
        max(1, int(available_h * MAX_CONTENT_HEIGHT_SCREEN_FRACTION)),
    )

    aspect = video_width / max(1, video_height)
    min_plot_h = min(MIN_PLOT_HEIGHT, max(1, max_content_h // 4))
    plot_h = min(DEFAULT_PLOT_HEIGHT, max(min_plot_h, int(max_content_h * 0.12)))
    available_video_h = max(1, max_content_h - 2 * plot_h - CONTROL_BAR_HEIGHT)

    target_w = min(video_width, max_content_w)
    target_h = int(round(target_w / aspect))

    if target_h > available_video_h:
        target_h = available_video_h
        target_w = int(round(target_h * aspect))

    target_w = max(1, int(target_w))
    target_h = max(1, int(target_h))

    return {
        'video_width': target_w,
        'video_height': target_h,
        'plot_width': target_w,
        'waveform_height': plot_h,
        'velocity_height': plot_h,
        'control_height': CONTROL_BAR_HEIGHT,
        'content_width': target_w,
        'content_height': target_h + CONTROL_BAR_HEIGHT + 2 * plot_h,
    }

def build_waveform_image(audio_signal, sr, width, height, audio_channel, bg=(24, 24, 24), fg=(230, 230, 230)):

    img = np.full((height, width, 3), bg, dtype=np.uint8)

    if audio_signal is None or sr is None:
        cv2.putText(img, 'No audio data', (10, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return img

    audio_signal = audio_signal[audio_channel, :]

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

def build_spectrogram_image(audio_signal, sr, width, height, audio_channel,
                            bg=(24, 24, 24),
                            nfft=1024, noverlap=768, max_freq=None):
    if audio_signal is None or sr is None:
        img = np.full((height, width, 3), bg, dtype=np.uint8)
        cv2.putText(img, 'No audio data', (10, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return img

    x = audio_signal[audio_channel, :].astype(np.float32)

    dpi = 100
    fig_w = max(1, int(width)) / dpi
    fig_h = max(1, int(height)) / dpi
    fig = plt.Figure(figsize=(fig_w, fig_h), dpi=dpi)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_axes([0, 0, 1, 1])

    fig.patch.set_facecolor(np.array(bg) / 255.0)
    ax.set_facecolor(np.array(bg) / 255.0)

    Pxx, freqs, bins, im = ax.specgram(
        x,
        NFFT=nfft,
        Fs=sr,
        noverlap=noverlap,
        scale='dB',
        mode='psd',
        window=np.hanning(nfft),
        cmap='magma'
    )

    db = 10.0 * np.log10(Pxx + 1e-12)

    vmax = np.percentile(db, 99.5)
    vmin = vmax - 80.0
    im.set_clim(vmin, vmax)

    if max_freq is not None:
        ax.set_ylim(0, max_freq)
    else:
        ax.set_ylim(0, sr / 2)

    ax.set_axis_off()

    canvas.draw()
    buf = np.frombuffer(canvas.buffer_rgba(), dtype=np.uint8)
    img_rgba = buf.reshape(int(height), int(width), 4)
    img_bgr = cv2.cvtColor(img_rgba, cv2.COLOR_RGBA2BGR)

    return img_bgr

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

    # Required check because of legacy files
    if 'velocity_cm/s' in df.columns:
        df['velocity'] = df['velocity_cm/s']

    velocity_original = df['velocity'].copy()
    df['velocity'] = df['velocity'].rolling(window=3, center=True).mean()
    df['velocity'] = df['velocity'].fillna(velocity_original)

    frames = df['Frame'].to_numpy(dtype=np.int64)
    velocities = df['velocity'].fillna(0).to_numpy(dtype=np.float32)

    v_max = np.nanmax(velocities)
    v_min = np.nanmin(velocities)
    v_abs_max = float(np.nanmax(np.abs(velocities)))
    v_norm = np.clip(velocities / v_abs_max, -1.0, 1.0)

    total_frames = frames.shape[0]
    pts = []
    for frame, val in zip(frames, v_norm):
        x = int((frame - 1) * (width - 1) / max(1, total_frames - 1))
        y = int((1 - (val + 1) / 2) * (height - 1))
        pts.append((x, y))

    cv2.line(img, (0, height // 2), (width - 1, height // 2), axis, 1)

    cv2.polylines(img, [np.array(pts, dtype=np.int32)], False, line, 1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.3
    font_color = (50, 100, 50)
    thickness = 1
    margin_left = 5

    label_top = f"{v_max:.1f} cm/s"
    label_center = "0 cm/s"
    label_bottom = f"{v_min:.1f} cm/s"

    cv2.putText(img, label_top, (margin_left, 15), font, font_scale, font_color, thickness)
    cv2.putText(img, label_center, (margin_left, height // 2 - 5), font, font_scale, font_color, thickness)
    cv2.putText(img, label_bottom, (margin_left, height - 5), font, font_scale, font_color, thickness)

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

def merge_annotations(video_path, new_annotations, audio_path, should_update_audio):
    original_video_file = os.path.basename(video_path)
    json_filename = get_json_filename(original_video_file)

    parent_folder = os.path.dirname(os.path.dirname(video_path))
    annotations_folder = os.path.join(parent_folder, "annotations")
    json_path = os.path.join(annotations_folder, json_filename)

    existing_data = {}
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)

    existing_data["video_file"] = original_video_file
    if should_update_audio:
        existing_data['audio_file'] = os.path.basename(audio_path)
        
    if "video_annotations" not in existing_data:
        existing_data["video_annotations"] = {}
    if "audio_annotations" not in existing_data and should_update_audio:
        existing_data["audio_annotations"] = {}

    for k, v in new_annotations.items():
        if v["frame"] is not None and v["time"] is not None:
            existing_data["video_annotations"][k] = {"time": v["time"], "frame": v["frame"]}

        if v['sample'] is not None and should_update_audio:
            existing_data["audio_annotations"][k] = {"time": v["time"], "sample": int(v["sample"])}

    os.makedirs(annotations_folder, exist_ok=True)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=4)
        print(f"Annotations for {video_path} updated in {json_path}.")

def update_annotations(annotations, event_number, annotation):
    print(f"Event {event_number} annotated at frame {annotation[0]}, time {annotation[1]:.2f}s")
    frame = annotation[0]
    time = annotation[1]
    sample = time * annotation[2] if annotation[2] is not None else None
    annotations[str(event_number)] = {
        "frame": frame,
        "time": time,
        "sample": sample
    }

zoom_level = 1.0
zoom_center = None
last_frame = None
display_video_size = None
source_video_size = None
control_regions = {}
speed_slider_dragging = False

def _point_in_rect(x, y, rect):
    x1, y1, x2, y2 = rect
    return x1 <= x <= x2 and y1 <= y <= y2

def _set_playback_speed_from_x(x):
    global playback_speed

    slider_rect = control_regions.get('speed_slider')
    if not slider_rect:
        return

    x1, _, x2, _ = slider_rect
    ratio = (x - x1) / max(1, x2 - x1)
    ratio = max(0.0, min(1.0, ratio))
    playback_speed = max(1, int(round(ratio * 100)))

def build_control_bar(width, height, top_y):
    bar = np.full((height, width, 3), (36, 36, 36), dtype=np.uint8)
    cv2.line(bar, (0, 0), (width - 1, 0), (70, 70, 70), 1)
    cv2.line(bar, (0, height - 1), (width - 1, height - 1), (70, 70, 70), 1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    text_color = (235, 235, 235)
    muted = (165, 165, 165)
    selected = (70, 125, 190)
    button_border = (105, 105, 105)

    button_h = 26
    y1 = max(6, (height - button_h) // 2)
    y2 = y1 + button_h
    wave_rect = (10, y1, 78, y2)
    spec_rect = (84, y1, 152, y2)

    for rect, label, selected_mode in ((wave_rect, 'Wave', 0), (spec_rect, 'Spec', 1)):
        color = selected if show_mode == selected_mode else (48, 48, 48)
        cv2.rectangle(bar, (rect[0], rect[1]), (rect[2], rect[3]), color, -1)
        cv2.rectangle(bar, (rect[0], rect[1]), (rect[2], rect[3]), button_border, 1)
        cv2.putText(bar, label, (rect[0] + 10, rect[1] + 18), font, 0.48, text_color, 1, cv2.LINE_AA)

    speed_label_x = 170
    cv2.putText(bar, f'Speed {playback_speed}%', (speed_label_x, y1 + 18), font, 0.48, text_color, 1, cv2.LINE_AA)

    slider_x1 = min(width - 120, 285)
    slider_x1 = max(speed_label_x + 96, slider_x1)
    slider_x2 = width - 22
    slider_y = height // 2

    if slider_x2 - slider_x1 >= 40:
        cv2.line(bar, (slider_x1, slider_y), (slider_x2, slider_y), muted, 2)
        knob_x = int(slider_x1 + (playback_speed / 100.0) * (slider_x2 - slider_x1))
        cv2.circle(bar, (knob_x, slider_y), 7, selected, -1)
        cv2.circle(bar, (knob_x, slider_y), 7, (230, 230, 230), 1)
        speed_rect = (slider_x1, top_y + slider_y - 12, slider_x2, top_y + slider_y + 12)
    else:
        speed_rect = None

    return bar, {
        'wave': (wave_rect[0], top_y + wave_rect[1], wave_rect[2], top_y + wave_rect[3]),
        'spec': (spec_rect[0], top_y + spec_rect[1], spec_rect[2], top_y + spec_rect[3]),
        'speed_slider': speed_rect,
    }

def get_zoomed_frame(frame, zoom_level, center=None, output_size=None):
    h, w = frame.shape[:2]

    if zoom_level <= 1.0:
        if output_size is None or output_size == (w, h):
            return frame
        interpolation = cv2.INTER_AREA if output_size[0] < w or output_size[1] < h else cv2.INTER_LINEAR
        return cv2.resize(frame, output_size, interpolation=interpolation)

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
    output_size = output_size or (w, h)
    zoomed_frame = cv2.resize(cropped, output_size, interpolation=cv2.INTER_LINEAR)

    return zoomed_frame

def mouse_callback(event, x, y, flags, param):
    global zoom_level, zoom_center, last_frame, show_mode, speed_slider_dragging

    if event == cv2.EVENT_LBUTTONDOWN:
        if control_regions.get('wave') and _point_in_rect(x, y, control_regions['wave']):
            show_mode = 0
            return
        if control_regions.get('spec') and _point_in_rect(x, y, control_regions['spec']):
            show_mode = 1
            return
        if control_regions.get('speed_slider') and _point_in_rect(x, y, control_regions['speed_slider']):
            speed_slider_dragging = True
            _set_playback_speed_from_x(x)
            return

    if event == cv2.EVENT_MOUSEMOVE and speed_slider_dragging:
        if flags & cv2.EVENT_FLAG_LBUTTON:
            _set_playback_speed_from_x(x)
        else:
            speed_slider_dragging = False
        return

    if event == cv2.EVENT_LBUTTONUP:
        if speed_slider_dragging:
            _set_playback_speed_from_x(x)
        speed_slider_dragging = False
        return

    if event == cv2.EVENT_MOUSEWHEEL and display_video_size and y < display_video_size[1]:
        if flags > 0:  # Scroll up
            zoom_level = min(zoom_level + 0.2, 5.0)
        else:  # Scroll down
            zoom_level = max(zoom_level - 0.2, 1.0)
        if display_video_size and source_video_size:
            display_w, display_h = display_video_size
            source_w, source_h = source_video_size
            if 0 <= x < display_w and 0 <= y < display_h:
                zoom_center = (
                    int(x * source_w / max(1, display_w)),
                    int(y * source_h / max(1, display_h)),
                )
        else:
            zoom_center = (x, y)

        if last_frame is not None:
            get_zoomed_frame(last_frame, zoom_level, zoom_center, display_video_size)

def annotate_video(video_path, audio_path, labelled_position_path, audio_channel):
    global zoom_level, zoom_center, last_frame, ctrl_pressed, event_key, display_video_size, source_video_size, control_regions
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

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    cv2.setMouseCallback(WINDOW_NAME, mouse_callback)

    annotations = {}
    e1_frame = e2_frame = e3_frame = e4_frame = e5_frame = e6_frame = e7_frame = e8_frame = None
    paused = False
    frame_buffer = []
    buf_i = -1
    key_pressed = None
    quit_app = False
    go_prev = False

    json_filename = get_json_filename(os.path.basename(video_path))
    parent_folder = os.path.dirname(os.path.dirname(video_path))
    annotations_folder = os.path.join(parent_folder, "annotations")
    json_path = os.path.join(annotations_folder, json_filename)
    existing_annotations_title = ""
    video_existing_annotations = {}

    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
            if "video_annotations" in existing_data:
                video_existing_annotations = existing_data["video_annotations"]
                existing_annotations_title = " | Existing :"
                for key, value in video_existing_annotations.items():
                    frame = value.get("frame")
                    time = value.get("time")
                    if frame is not None and time is not None:
                        existing_annotations_title += f" {key}: F(T): {frame}({time:.2f}s)"


    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    buf_i = 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    vh, vw = (int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)), int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
    layout = calculate_display_layout(vw, vh)
    display_video_size = (layout['video_width'], layout['video_height'])
    source_video_size = (vw, vh)
    waveform_h = layout['waveform_height']
    velocity_h = layout['velocity_height']
    control_h = layout['control_height']
    plot_w = layout['plot_width']

    base_waveform = build_waveform_image(audio_data, audio_sr, plot_w, waveform_h, audio_channel)
    base_spectrogram = build_spectrogram_image(audio_data, audio_sr, plot_w, waveform_h, audio_channel, nfft=512, noverlap=384, max_freq=None)
    velocity_plot = build_velocity_image(labelled_position_path, plot_w, velocity_h)

    audio_player = AudioPlayer(audio_data, audio_sr, audio_channel)
    audio_player.play(0)

    while True:

        if cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
            quit_app = True
            break

        if not frame_buffer:
            ret, frame = cap.read()
            if not ret:
                paused = True
                continue
            frame_buffer.append(frame)

        if not paused:
            if buf_i < len(frame_buffer) - 1:
                buf_i += 1
            else:
                ret, frame = cap.read()
                if not ret:
                    paused = True
                else:
                    frame_buffer.append(frame)
                    buf_i += 1

        frame = frame_buffer[buf_i]
        last_frame = frame.copy()

        frame_index = buf_i
        time_in_seconds = frame_index / fps

        display_frame = get_zoomed_frame(frame, zoom_level, zoom_center, display_video_size)

        if show_mode == 0:
            sp = base_waveform.copy()
        else:
            sp = base_spectrogram.copy()
        if audio_duration > 0:
            draw_playhead(sp, time_in_seconds, audio_duration)
        vel = velocity_plot.copy()
        if labelled_position_path and os.path.exists(labelled_position_path):
            draw_playhead(vel, frame_index, total_frames - 1)

        controls, control_regions = build_control_bar(plot_w, control_h, display_frame.shape[0])
        combined = np.vstack([display_frame, controls, sp, vel])

        title_text = f'{os.path.basename(video_path)} | {frame_index}({time_in_seconds:.2f}s){existing_annotations_title}'
        if e1_frame is not None:
            title_text += f' | New : E1 F(T): {e1_frame}({e1_time:.2f}s)'
        if e2_frame is not None and e1_frame is not None and e1_frame<e2_frame:
            title_text += f' | E2 F(T): {e2_frame}({e2_time:.2f}s)'
        if e3_frame is not None and e2_frame is not None and e2_frame<=e3_frame and e1_frame<e2_frame:
            title_text += f' | E3 F(T): {e3_frame}({e3_time:.2f}s)'
        if e4_frame is not None and e3_frame is not None and e3_frame<=e4_frame and e2_frame<=e3_frame:
            title_text += f' | E4 F(T): {e4_frame}({e4_time:.2f}s)'
        if e5_frame is not None and e4_frame is not None and e4_frame<=e5_frame:
            title_text += f' | E5 F(T): {e5_frame}({e5_time:.2f}s)'
        if e6_frame is not None and e5_frame is not None and e5_frame<=e6_frame:
            title_text += f' | E6 F(T): {e6_frame}({e6_time:.2f}s)'
        if e7_frame is not None and e6_frame is not None and e6_frame<=e7_frame:
            title_text += f' | E7 F(T): {e7_frame}({e7_time:.2f}s)'
        if e8_frame is not None and e7_frame is not None and e7_frame<=e8_frame:
            title_text += f' | E8 F(T): {e8_frame}({e8_time:.2f}s)'

        cv2.setWindowTitle(WINDOW_NAME, title_text)
        cv2.imshow(WINDOW_NAME, combined)
        speed_val = max(1, playback_speed)
        wait_ms = int(33 / (speed_val / 100.0))
        key = cv2.waitKey(wait_ms)

        if key == 27:  # ESC
            quit_app = True
            break
        elif key == 32:  # Space pause/play
            paused = not paused
            if paused:
                audio_player.pause()
            else:
                audio_player.play(time_in_seconds)
        elif key == ord('r'):  # Reset zoom
            zoom_level = 1.0
            zoom_center = None
        elif key == ord('1') and not ctrl_pressed:
            e1_frame = frame_index; e1_time = time_in_seconds
            if e2_frame is not None and e1_frame > e2_frame:
                e2_frame = e3_frame = e4_frame = e5_frame = e6_frame = e7_frame = e8_frame = None
            update_annotations(annotations, 1, (e1_frame, e1_time, audio_sr))
        elif key == ord('2') and not ctrl_pressed and e1_frame is not None:
            e2_frame = frame_index; e2_time = time_in_seconds
            if e2_frame < e1_frame:
                e2_frame = e3_frame = e4_frame = e5_frame = e6_frame = e7_frame = e8_frame = None
            update_annotations(annotations, 2, (e2_frame, e2_time, audio_sr))
        elif key == ord('3') and not ctrl_pressed and e2_frame is not None:
            e3_frame = frame_index; e3_time = time_in_seconds
            if e3_frame < e2_frame:
                e3_frame = e4_frame = e5_frame = e6_frame = e7_frame = e8_frame = None
            update_annotations(annotations, 3, (e3_frame, e3_time, audio_sr))
        elif key == ord('4') and not ctrl_pressed and e3_frame is not None:
            e4_frame = frame_index; e4_time = time_in_seconds
            if e4_frame < e3_frame:
                e4_frame = e5_frame = e6_frame = e7_frame = e8_frame = None
            update_annotations(annotations, 4, (e4_frame, e4_time, audio_sr))
        elif key == ord('5') and not ctrl_pressed and e4_frame is not None:
            e5_frame = frame_index; e5_time = time_in_seconds
            if e5_frame < e4_frame:
                e5_frame = e6_frame = e7_frame = e8_frame = None
            update_annotations(annotations, 5, (e5_frame, e5_time, audio_sr))
        elif key == ord('6') and not ctrl_pressed and e5_frame is not None:
            e6_frame = frame_index; e6_time = time_in_seconds
            if e6_frame < e5_frame:
                e6_frame = e7_frame = e8_frame = None
            update_annotations(annotations, 6, (e6_frame, e6_time, audio_sr))
        elif key == ord('7') and not ctrl_pressed and e6_frame is not None:
            e7_frame = frame_index; e7_time = time_in_seconds
            if e7_frame < e6_frame:
                e7_frame = e8_frame = None
            update_annotations(annotations, 7, (e7_frame, e7_time, audio_sr))
        elif key == ord('8') and not ctrl_pressed and e7_frame is not None:
            e8_frame = frame_index; e8_time = time_in_seconds
            if e8_frame < e7_frame:
                e8_frame = None
            update_annotations(annotations, 8, (e8_frame, e8_time, audio_sr))

        elif event_key == '1' and ctrl_pressed and "1" in video_existing_annotations:
            print("Restoring event 1 from existing annotations")
            e1_frame = video_existing_annotations["1"]["frame"]; e1_time = video_existing_annotations["1"]["time"]
            update_annotations(annotations, 1, (e1_frame, e1_time, audio_sr))
        elif event_key == '2' and ctrl_pressed and "2" in video_existing_annotations:
            e2_frame = video_existing_annotations["2"]["frame"]; e2_time = video_existing_annotations["2"]["time"]
            update_annotations(annotations, 2, (e2_frame, e2_time, audio_sr))
        elif event_key == '3' and ctrl_pressed and "3" in video_existing_annotations:
            e3_frame = video_existing_annotations["3"]["frame"]; e3_time = video_existing_annotations["3"]["time"]
            update_annotations(annotations, 3, (e3_frame, e3_time, audio_sr))
        elif event_key == '4' and ctrl_pressed and "4" in video_existing_annotations:
            e4_frame = video_existing_annotations["4"]["frame"]; e4_time = video_existing_annotations["4"]["time"]
            update_annotations(annotations, 4, (e4_frame, e4_time, audio_sr))
        elif event_key == '5' and ctrl_pressed and "5" in video_existing_annotations:
            e5_frame = video_existing_annotations["5"]["frame"]; e5_time = video_existing_annotations["5"]["time"]
            update_annotations(annotations, 5, (e5_frame, e5_time, audio_sr))
        elif event_key == '6' and ctrl_pressed and "6" in video_existing_annotations:
            e6_frame = video_existing_annotations["6"]["frame"]; e6_time = video_existing_annotations["6"]["time"]
            update_annotations(annotations, 6, (e6_frame, e6_time, audio_sr))
        elif event_key == '7' and ctrl_pressed and "7" in video_existing_annotations:
            e7_frame = video_existing_annotations["7"]["frame"]; e7_time = video_existing_annotations["7"]["time"]
            update_annotations(annotations, 7, (e7_frame, e7_time, audio_sr))
        elif event_key == '8' and ctrl_pressed and "8" in video_existing_annotations:
            e8_frame = video_existing_annotations["8"]["frame"]; e8_time = video_existing_annotations["8"]["time"]
            update_annotations(annotations, 8, (e8_frame, e8_time, audio_sr))
        elif key == ord('n'):
            break
        elif key == ord('p'):
            go_prev = True
            break
        elif key == ord('c'):
            e1_frame = e2_frame = e3_frame = e4_frame = e5_frame = e6_frame = e7_frame = e8_frame = None
            e1_time = e2_time = e3_time = e4_time = e5_time = e6_time = e7_time = e8_time = None
            annotations.clear()

        if key == ord('a'): key_pressed = 'a'
        elif key == ord('d'): key_pressed = 'd'
        elif key == -1: key_pressed = None

        if key_pressed == 'a' and paused:
            if buf_i > 0:
                buf_i -= 1
                audio_player.seek(buf_i / fps)
        elif key_pressed == 'd' and paused:
            if buf_i < len(frame_buffer) - 1:
                buf_i += 1
                audio_player.seek(buf_i / fps)
            else:
                ret, frame = cap.read()
                if ret:
                    frame_buffer.append(frame.copy())
                    buf_i += 1
                    audio_player.seek(buf_i / fps)
                else:
                    paused = True

    audio_player.stop()

    cap.release()
    cv2.destroyAllWindows()

    if annotations:
        should_update_audio = False
        if audio_path is not None and os.path.exists(audio_path):
            should_update_audio = durations_match(total_frames, audio_sr, audio_data)
        merge_annotations(video_path, annotations, audio_path, should_update_audio)
    else:
        print(f"No annotations made for {video_path}.")

    if mp4_path != video_path:
        os.remove(mp4_path)

    if quit_app:
        return 'quit'
    elif go_prev:
        return 'prev'
    else:
        return 'next'



def process_videos_in_folder(video_path, audio_path, labelled_position_path, audio_channel):

    videos = sorted([f for f in os.listdir(video_path) if f.lower().endswith(('.mp4', '.webm'))])

    i = 0
    while 0 <= i < len(videos):
        video_file = videos[i]
        file_basename, ext = os.path.splitext(video_file)
        video_file_path = os.path.join(video_path, file_basename + ext)
        audio_file_path = os.path.join(audio_path, file_basename + '.wav') if audio_path else None
        labelled_position_file_path = os.path.join(labelled_position_path, file_basename + '.csv') if labelled_position_path else None
        result = annotate_video(video_file_path, audio_file_path, labelled_position_file_path, audio_channel)
        if result == 'quit':
            break
        elif result == 'prev':
            i = max(0, i - 1)
        else:
            i += 1

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

    keyboard_listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
    keyboard_listener.daemon = True
    keyboard_listener.start()

    process_videos_in_folder(video_path, audio_path, labelled_position_path, audio_channel)

if __name__ == "__main__":
    main()
