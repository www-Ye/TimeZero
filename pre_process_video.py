# preprocess_dataset.py
import os
import json
import torch
from datasets import Dataset, DatasetDict
from qwen_vl_utils import process_vision_info
from transformers import AutoProcessor
from tqdm import tqdm
import multiprocessing as mp

MODEL_NAME = "/share/pretrain/mllm/Qwen2.5-VL-7B-Instruct"
OUTPUT_DIR = "./[DATASET]_preprocessed_data_maxpix_[MAX_PIX]"

def preprocess_single_video(task_args): # Accept task arguments as a single tuple/list
    video_path, processor, max_pixels, min_pixels, example_output_dir, sentence, solution, duration = task_args # Unpack task args
    try:
        image_inputs, video_inputs, video_kwargs, fps_inputs = preprocess_video_inner(
            video_path, processor, max_pixels, min_pixels
        )

        os.makedirs(example_output_dir, exist_ok=True)

        # torch.save(image_inputs, os.path.join(example_output_dir, "image_inputs.pt"))
        torch.save(video_inputs, os.path.join(example_output_dir, "video_inputs.pt"))
        with open(os.path.join(example_output_dir, "video_kwargs.json"), 'w') as f:
            json.dump(video_kwargs, f)

        return {
            "problem": sentence,
            "solution": solution,
            "preprocessed_path": example_output_dir,
            "duration": duration,
            "status": "success"
        }
    except Exception as e:
        print(f"Warning: Preprocessing failed for video {video_path}, skipping. Error: {e}")
        return {
            "video_path": video_path,
            "status": "failed",
            "error": str(e)
        }


def preprocess_video_inner(video_path, processor, max_pixels, min_pixels):
    messages = [
        {"role": "user", "content": [
                {"type": "video", 
                "video": video_path, 
                "total_pixels": max_pixels, 
                "min_pixels": min_pixels,
                },
            ]
        },
    ]
    image_inputs, video_inputs, video_kwargs = process_vision_info([messages], return_video_kwargs=True)
    fps_inputs = video_kwargs['fps']
    return image_inputs, video_inputs, video_kwargs, fps_inputs

def process_split(file_path, split_name, video_folder, output_dir, max_pixels, min_pixels, processor, num_workers=8):
    output_split_dir = os.path.join(output_dir, split_name)
    os.makedirs(output_split_dir, exist_ok=True)

    with open(file_path, 'r') as f:
        data = json.load(f)  

    examples = []
    tasks = []

    for video_id, video_data in data.items():
        for sentence_id, (timestamps, sentence) in enumerate(zip(video_data['timestamps'], video_data['sentences'])):
            try:
                sentence = sentence.strip().lower()
            except:
                import pdb; pdb.set_trace()
            if sentence.endswith("."):
                sentence = sentence[:-1]

            video_filename_base = video_id
            video_path = None
            for ext in ['mp4', 'mkv', 'webm']:
                candidate_path = os.path.join(video_folder, f"{video_filename_base}.{ext}")
                if os.path.isfile(candidate_path):
                    video_path = candidate_path
                    break
            if video_path is None:
                print(f"Warning: Video file not found for ID: {video_id}")
                continue

            example_output_dir = os.path.join(output_split_dir, f"{video_id}_{sentence_id}")
            solution = (timestamps[0] / video_data['duration'], timestamps[1] / video_data['duration'])
            duration = video_data['duration']

            tasks.append((video_path, processor, max_pixels, min_pixels, example_output_dir, sentence, solution, duration)) # Prepare task arguments as tuples

    pbar = tqdm(total=len(tasks), desc=f"Preprocessing {split_name} split") # Initialize progress bar in main process

    with mp.Pool(processes=num_workers) as pool:
        results = pool.imap_unordered(preprocess_single_video, tasks) # Use imap_unordered for unordered results, potentially faster

        successful_examples = []
        failed_count = 0
        for result in results: # Iterate through results to update progress bar
            pbar.update(1)
            if result['status'] == 'success':
                successful_examples.append(result)
            else:
                failed_count += 1
                # Optionally log failed videos and errors

    pbar.close() # Close progress bar after processing

    print(f"Preprocessing for split '{split_name}' finished. Failed videos: {failed_count}, Successful videos: {len(successful_examples)}")

    return Dataset.from_list(successful_examples)


def preprocess_dataset_and_save(train_data_path, eval_data_path, video_folder, output_dir, max_pixels, min_pixels, num_workers=8):

    processor = AutoProcessor.from_pretrained(MODEL_NAME)

    os.makedirs(output_dir, exist_ok=True)

    train_dataset = process_split(train_data_path, "train", video_folder, output_dir, max_pixels, min_pixels, processor, num_workers)
    eval_dataset = process_split(eval_data_path, "eval", video_folder, output_dir, max_pixels, min_pixels, processor, num_workers)
    return DatasetDict({"train": train_dataset, "eval": eval_dataset})


if __name__ == "__main__":
    train_data_path = "./Charades/charades_annotation/train.json"
    eval_data_path = "./Charades/charades_annotation/val.json"
    video_folder = "./Charades/Charades_v1"
    output_dir = OUTPUT_DIR.replace('[DATASET]', 'charades').replace('[MAX_PIX]', '3584')
    
    print('output_dir', output_dir)
    max_pixels = 3584 * 28 * 28
    min_pixels = 16 * 28 * 28
    num_workers = 16

    dataset_dict = preprocess_dataset_and_save(
        train_data_path, eval_data_path, video_folder, output_dir, max_pixels, min_pixels, num_workers=num_workers
    )
    print("Preprocessing complete. Datasets saved to:", output_dir)
    print(dataset_dict)