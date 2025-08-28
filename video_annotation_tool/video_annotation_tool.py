import cv2
import argparse
import json
import os
import subprocess

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

def merge_annotations(video_path, new_annotations):
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

    existing_data["video_annotations"].update(new_annotations)

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=4)
        print(f"Annotations for {video_path} updated in {json_path}.")

def update_annotations(annotations, *frames_times):
    for i, (frame, time) in enumerate(frames_times, start=1):
        annotations[str(i)] = {"frame": frame, "time": time}

zoom_level = 1.0
zoom_center = None
last_frame = None

def show_zoomed_frame(window_name, frame, zoom_level, center=None):
    h, w = frame.shape[:2]

    if zoom_level <= 1.0:
        cv2.imshow(window_name, frame)
        return

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

    cv2.imshow(window_name, zoomed_frame)

def mouse_callback(event, x, y, flags, param):
    global zoom_level, zoom_center, last_frame

    if event == cv2.EVENT_MOUSEWHEEL:
        if flags > 0:  # Scroll up
            zoom_level = min(zoom_level + 0.2, 5.0)
        else:  # Scroll down
            zoom_level = max(zoom_level - 0.2, 1.0)
        zoom_center = (x, y)

        if last_frame is not None:
            show_zoomed_frame('Video Annotation', last_frame, zoom_level, zoom_center)

def annotate_video(video_path):
    global zoom_level, zoom_center, last_frame
    mp4_path = convert_video_to_h264(video_path)
    cap = cv2.VideoCapture(mp4_path)

    if not cap.isOpened():
        print("Error: Could not open video.")
        return

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

    while True:
        if not paused:
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            last_frame = frame.copy()
            show_zoomed_frame('Video Annotation', frame, zoom_level, zoom_center)
            frame_buffer.append(frame)

        frame_index = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        time_in_seconds = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

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
            update_annotations(annotations, (e1_frame, e1_time), (e2_frame, e2_time), (e3_frame, e3_time), (e4_frame, e4_time))
        elif key == ord('5') and "1" in existing_annotations:
            e1_frame = existing_annotations["1"]["frame"]; e1_time = existing_annotations["1"]["time"]
        elif key == ord('6') and "2" in existing_annotations:
            e2_frame = existing_annotations["2"]["frame"]; e2_time = existing_annotations["2"]["time"]
        elif key == ord('7') and "3" in existing_annotations:
            e3_frame = existing_annotations["3"]["frame"]; e3_time = existing_annotations["3"]["time"]
        elif key == ord('8') and "4" in existing_annotations:
            e4_frame = existing_annotations["4"]["frame"]; e4_time = existing_annotations["4"]["time"]
            update_annotations(annotations, (e1_frame, e1_time), (e2_frame, e2_time), (e3_frame, e3_time), (e4_frame, e4_time))
        elif key == ord('n'):
            break
        elif key == ord('c'):
            e1_frame = e2_frame = e3_frame = e4_frame = None
            e1_time = e2_time = e3_time = e4_time = None
            update_annotations(annotations, (e1_frame, e1_time), (e2_frame, e2_time), (e3_frame, e3_time), (e4_frame, e4_time))

        if key == ord('a'): key_pressed = 'a'
        elif key == ord('d'): key_pressed = 'd'
        elif key == -1: key_pressed = None

        if key_pressed == 'a' and paused:
            if len(frame_buffer) > 0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, cap.get(cv2.CAP_PROP_POS_FRAMES) - 2)
                ret, frame = cap.read()
                if ret:
                    last_frame = frame.copy()
                    show_zoomed_frame('Video Annotation', frame, zoom_level, zoom_center)
                    frame_buffer.pop()
        elif key_pressed == 'd' and paused:
            ret, frame = cap.read()
            if ret:
                last_frame = frame.copy()
                show_zoomed_frame('Video Annotation', frame, zoom_level, zoom_center)
                frame_buffer.append(frame)

    cap.release()
    cv2.destroyAllWindows()

    if annotations:
        merge_annotations(video_path, annotations)
    else:
        print(f"No annotations made for {video_path}.")

    if mp4_path != video_path:
        os.remove(mp4_path)

    return quit_app


def process_videos_in_folder(folder_path):
    video_files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f)) and f.lower().endswith(('.mp4', '.webm'))]
    for video_file in video_files:
        video_path = os.path.join(folder_path, video_file)
        quit_app = annotate_video(video_path)
        if quit_app:
            break

def main():
    parser = argparse.ArgumentParser(description='Annotate time instants in videos in a folder.')
    parser.add_argument('folder_path', type=str, help='Path to the folder containing video files')
    args = parser.parse_args()
    process_videos_in_folder(args.folder_path)

if __name__ == "__main__":
    main()