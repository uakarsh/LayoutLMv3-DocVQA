from tqdm import tqdm
import editdistance
from collections import defaultdict
from datasets import DatasetDict, Dataset
from src.utils import read_data
from preprocess.utils import get_answer_indices,clean_text, anls_metric_str, better_subfinder, get_answer_indices_by_enumeration

from datasets import load_from_disk
"""
    Convert the DocVQA dataset into dataset cache, which is a dictionary of Dataset objects.
    At the same time, we extract the answer spans.
"""


def extract_start_end_index_v1(current_answers, words):
    """
    Adapted from https://github.com/anisha2102/docvqa/blob/master/create_dataset.py
    :param current_answers:
    :param words:
    :return:
    """
    ## extracting the start, end index
    processed_answers = []
    ## remove duplicates because of the case of multiple answers
    current_answers = list(set(current_answers))
    all_not_found = True
    for ans_index in range(len(current_answers)):
        current_ans = current_answers[ans_index]
        start_index, end_index, extracted_answer = get_answer_indices(words, current_answers[ans_index])
        ans = current_ans.lower()
        extracted_answer = clean_text(extracted_answer)
        ans = clean_text(ans)
        dist = editdistance.eval(extracted_answer.replace(' ', ''),
                                 ans.replace(' ', '')) if extracted_answer != None else 1000
        if start_index == -1:
            start_index = -1
            end_index = -1
            extracted_answer = ""
        if dist > 5:
            start_index = -1
            end_index = -1
        if start_index == -1 or len(extracted_answer) > 150 or extracted_answer == "":
            start_index = -1
            end_index = -1
            extracted_answer = ""
        if start_index != -1:
            all_not_found = False
        processed_answers.append({
            "start_word_position": start_index,
            "end_word_position": end_index,
            "gold_answer": current_ans,
            "extracted_answer": extracted_answer})
    return processed_answers, all_not_found

def extract_start_end_index_v2(current_answers, words):
    """
    Follwing https://github.com/redthing1/layoutlm_experiments/blob/main/llm_tests/llm_tests/prep_docvqa_xqa.py.
    :param current_answers:
    :param words:
    :return:
    """
    ## extracting the start, end index
    processed_answers = []
    ## remove duplicates because of the case of multiple answers
    current_answers = list(set(current_answers))
    all_not_found = True
    for ans_index in range(len(current_answers)):
        current_ans = current_answers[ans_index]
        match, word_idx_start, word_idx_end = better_subfinder(
            words, current_ans.lower()
        )
        if not match:
            for i in range(len(current_ans)):
                if len(current_ans) == 1:
                    # this method won't work for single-character answers
                    break  # break inner loop
                # drop the ith character from the answer
                answer_i = current_ans[:i] + current_ans[i + 1:]
                # print('Trying: ', i, answer, answer_i, answer_i.lower().split())
                # check if we can find this one in the context
                match, word_idx_start, word_idx_end = better_subfinder(
                    words, answer_i.lower(), try_hard=True
                )
                if match:
                    break  # break inner
        if match:
            assert word_idx_start != -1 and word_idx_end != -1
            extracted_answer = " ".join(words[word_idx_start:word_idx_end + 1])
        else:
            word_idx_start = -1
            word_idx_end = -1
            extracted_answer = ""
        ## end index is inclusive
        if word_idx_start != -1:
            all_not_found = False
        processed_answers.append({
            "start_word_position": word_idx_start,
            "end_word_position": word_idx_end,
            "gold_answer": current_ans,
            "extracted_answer": extracted_answer})
    return processed_answers, all_not_found

def extract_start_end_index_v3(current_answers, words, threshold = 3):
    """
    Directly enumerate all the spans, really expensive, there is a threshold of tolerance
    :param current_answers:
    :param words:
    :param threshold: for example, the length of answer token is L, we search all the spans
                        whose length is within [L-threshold, L+threshold]
    :return:
    """
    ## extracting the start, end index
    processed_answers = []
    ## remove duplicates because of the case of multiple answers
    current_answers = list(set(current_answers))
    all_not_found = True
    for ans_index in range(len(current_answers)):
        current_ans = current_answers[ans_index]
        start_index, end_index, extracted_answer = get_answer_indices_by_enumeration(words, current_answers[ans_index], threshold)
        ans = current_ans.lower()
        extracted_answer = clean_text(extracted_answer)
        ans = clean_text(ans)
        dist = editdistance.eval(extracted_answer.replace(' ', ''),
                                 ans.replace(' ', '')) if extracted_answer != None else 1000
        if start_index == -1:
            start_index = -1
            end_index = -1
            extracted_answer = ""
        if dist > 5:
            start_index = -1
            end_index = -1
        if start_index == -1 or len(extracted_answer) > 150 or extracted_answer == "":
            start_index = -1
            end_index = -1
            extracted_answer = ""
        if start_index != -1:
            all_not_found = False
        processed_answers.append({
            "start_word_position": start_index,
            "end_word_position": end_index,
            "gold_answer": current_ans,
            "extracted_answer": extracted_answer})
    return processed_answers, all_not_found

def normalize_bbox(bbox, width, height):
    return [
        int(1000 * (bbox[0] / width)),
        int(1000 * (bbox[1] / height)),
        int(1000 * (bbox[2] / width)),
        int(1000 * (bbox[3] / height)),
    ]

def convert_docvqa_to_cache(train_file, val_file, test_file, lowercase:bool, read_msr_ocr: bool = False,
                            extraction_method="v3") -> DatasetDict:
    data_dict = {}
    for file in [train_file, val_file, test_file]:
        new_all_data = defaultdict(list)
        data = read_data(file)
        split = data["dataset_split"]
        objs = data['data']
        num_answer_span_found = 0
        all_original_accepted = []
        all_extracted_not_clean = []
        msr_data = None
        msr_image_name2width_height = None
        if read_msr_ocr:
            if "test" not in split:
                msr_file = "data/docvqa_proc_train_t3_ocr" if split == "train" else "data/docvqa_proc_val_t3_msread_ocr"
                msr_data = load_from_disk(msr_file)
            else:
                msr_file = "data/docvqa/test/test_v1.0_msr.json"
                msr_data = read_data(msr_file)
        # # Note: for natural order:
        # if read_msr_ocr:
        #     image_name2width_height_file = f"data/docvqa/{split}_image_name2width_height.json"
        #     ocr_info_file = f"data/docvqa/{split}_v1.0_msr_order_natural_more_info.json"
        #     msr_data = read_data(ocr_info_file)
        #     msr_image_name2width_height = read_data(image_name2width_height_file)
        # # Note: for segment level:
        # if read_msr_ocr:
        #     ocr_info_file = f"data/docvqa/{split}/{split}_v1.0_msr_seg_True.json"
        #     msr_data = read_data(ocr_info_file)
        for obj_idx, obj in tqdm(enumerate(objs), desc="reading {}".format(split), total=len(objs)):
            msr_obj = None
            if msr_data is not None:
                msr_obj = msr_data[obj_idx]
                assert obj['questionId'] == msr_obj['questionId']
            new_answers = None
            for key in obj.keys():
                if key == "question":
                    new_all_data[key].append(obj[key].lower() if lowercase else obj[key])
                elif key == "answers":
                    answers = obj[key]
                    new_answers = []
                    for ans in answers:
                        new_answers.append(ans.lower() if lowercase else ans)
                    new_answers = list(set(new_answers))
                    ## not added yet, later after processing, we add start and end as well.
                    new_all_data["original_answer"].append(new_answers)
                else:
                    new_all_data[key].append(obj[key])
            if new_answers is None:
                # this only applies to test set.
                new_all_data["original_answer"].append(["dummy answer"])

            ocr_file = f"/kaggle/input/docvqa-dataset/{split}/{split}/ocr_results/{obj['ucsf_document_id']}_{obj['ucsf_document_page_no']}.json"
            ocr_data = read_data(ocr_file)
            assert len(ocr_data['recognitionResults']) == 1
            if msr_obj is None:
                all_text = ' '.join([line['text'] for line in ocr_data['recognitionResults'][0]['lines']])
                text, layout = [], []
                for line in ocr_data["recognitionResults"][0]["lines"]:
                    for word in line["words"]:
                        x1, y1, x2, y2, x3, y3, x4, y4 = word['boundingBox']
                        new_x1 = min([x1, x2, x3, x4])
                        new_x2 = max([x1, x2, x3, x4])
                        new_y1 = min([y1, y2, y3, y4])
                        new_y2 = max([y1, y2, y3, y4])
                        if word["text"].startswith("http") or word["text"] == "":
                            continue
                        text.append(word["text"].lower() if lowercase else word["text"])
                        layout.append([new_x1, new_y1, new_x2, new_y2])
            else:

                if msr_image_name2width_height is not None:
                    normalized_layout = []
                    image_name = msr_obj['image'].split('/')[1]
                    for coord in msr_obj['layout']:
                        normalized_layout.append(normalize_bbox(coord, msr_image_name2width_height[image_name]['width'], msr_image_name2width_height[image_name]['height']))
                    layout = normalized_layout
                else:
                    layout = msr_obj['boxes'] if "boxes" in msr_obj else msr_obj["layout"]
                all_text = ' '.join(msr_obj['words'])
                text = [word.lower() if lowercase else word for word in msr_obj['words']]

            new_all_data['ocr_text'].append(all_text)
            new_all_data['words'].append(text)
            new_all_data['layout'].append(layout)
            if new_answers is not None:
                ## lowercase everything for matching
                before_processed_text = [w.lower() for w in text]
                before_processed_new_answers = [a.lower() for a in new_answers]
                if extraction_method == "v1":
                    processed_answers, all_not_found = extract_start_end_index_v1(before_processed_new_answers, before_processed_text)
                elif extraction_method == "v2":
                    processed_answers, all_not_found = extract_start_end_index_v2(before_processed_new_answers, before_processed_text)
                elif extraction_method == "v1_v2":
                    processed_answers, all_not_found = extract_start_end_index_v1(before_processed_new_answers, before_processed_text)
                    if all_not_found:
                        processed_answers, _ = extract_start_end_index_v2(before_processed_new_answers, before_processed_text)
                elif extraction_method == "v2_v1":
                    processed_answers, all_not_found = extract_start_end_index_v2(before_processed_new_answers, before_processed_text)
                    if all_not_found:
                        processed_answers, _ = extract_start_end_index_v1(before_processed_new_answers, before_processed_text)
                elif extraction_method == "v3":
                    processed_answers, all_not_found = extract_start_end_index_v3(before_processed_new_answers, before_processed_text)
                
            else:
                processed_answers = [{
                    "start_word_position": -1,
                    "end_word_position": -1,
                    "gold_answer": "<NO_GOLD_ANSWER>",
                    "extracted_answer": ""}]
            new_all_data['processed_answers'].append(processed_answers)

            ## Note: just to count the stat
            for ans in processed_answers:
                if ans['start_word_position'] != -1:
                    num_answer_span_found += 1
                    break
            #NOTE: check the current extracted ANLS
            current_extracted_not_clean = []
            for ans in processed_answers:
                if ans['start_word_position'] != -1:
                    # candidate_tokens = text[ans['start_word_position']:ans['end_word_position']+1]
                    # candidate_tokens = [clean_text(x) for x in candidate_tokens]
                    current_extracted_not_clean.append(' '.join(text[ans['start_word_position']:ans['end_word_position']+1]))
            if len(current_extracted_not_clean) > 0:
                # _, anls = anls_metric_str(predictions=[current_extracted_not_clean], gold_labels=[new_answers])
                all_extracted_not_clean.append(current_extracted_not_clean)
                all_original_accepted.append(new_answers)
        # NOTE: check all extracted ANLS
        if "test" not in file:
            _, anls = anls_metric_str(predictions=all_extracted_not_clean, gold_labels=all_original_accepted)
            print(f"Current ANLS: {anls}")
        total_num = len(new_all_data["questionId"])
        print(f"{split} has {total_num} questions, "
              f"extractive answer found: {num_answer_span_found} "
              f"answer not found: {total_num - num_answer_span_found}", flush=True)
        data_dict[split] = Dataset.from_dict(new_all_data)
    all_data = DatasetDict(data_dict)
    return all_data



if __name__ == '__main__':
    all_lowercase = True
    read_msr = False ## default False, for data with MSR OCR, please contact me.
    answer_extraction_methods = ["v3"] ## default v1, v2, v1_v2, v2_v1
    for answer_extraction_method in answer_extraction_methods:
        dataset = convert_docvqa_to_cache("/kaggle/input/docvqa-dataset/train/train/train_v1.0.json",
                                          "/kaggle/input/docvqa-dataset/val/val/val_v1.0.json",
                                          "/kaggle/input/docvqa-dataset/test/test/test_v1.0.json",
                                          lowercase=all_lowercase,read_msr_ocr=read_msr,
                                          extraction_method=answer_extraction_method)
        cached_filename = f"./docvqa_cached_extractive_all_lowercase_{all_lowercase}_msr_{read_msr}_extraction_{answer_extraction_method}_enumeration"
        dataset.save_to_disk(cached_filename)

        ## for natural order
        # dataset = convert_docvqa_to_cache("data/docvqa/train/train_v1.0.json",
        #                                   "data/docvqa/val/val_v1.0.json",
        #                                   "data/docvqa/test/test_v1.0.json",
        #                                   lowercase=all_lowercase, read_msr_ocr=read_msr,
        #                                   extraction_method=answer_extraction_method)
        # cached_filename = f"data/docvqa_cached_extractive_all_lowercase_{all_lowercase}_msr_{read_msr}_extraction_{answer_extraction_method}_natural_order"
        # dataset.save_to_disk(cached_filename)

        ## segment useless
        # dataset = convert_docvqa_to_cache("data/docvqa/train/train_v1.0.json",
        #                                   "data/docvqa/val/val_v1.0.json",
        #                                   "data/docvqa/test/test_v1.0.json",
        #                                   lowercase=all_lowercase,read_msr_ocr=read_msr,
        #                                   extraction_method=answer_extraction_method)
        # cached_filename = f"data/docvqa_cached_extractive_all_lowercase_{all_lowercase}_msr_{read_msr}_extraction_{answer_extraction_method}_seg_level"
        # dataset.save_to_disk(cached_filename)