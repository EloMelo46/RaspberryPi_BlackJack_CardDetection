"""
This script is used to visualize YOLO annotations (bounding boxes and class labels) on playing card images.
It randomly selects images from a dataset, reads the corresponding YOLO label files (.txt), 
and draws the bounding boxes together with the card labels directly onto the images.
"""

import os, cv2, random
import matplotlib.pyplot as plt

Idx2Label = {i: name for i, name in enumerate([
    '10c', '10d', '10h', '10s', '2c', '2d', '2h', '2s',
    '3c', '3d', '3h', '3s', '4c', '4d', '4h', '4s',
    '5c', '5d', '5h', '5s', '6c', '6d', '6h', '6s',
    '7c', '7d', '7h', '7s', '8c', '8d', '8h', '8s',
    '9c', '9d', '9h', '9s', 'Ac', 'Ad', 'Ah', 'As',
    'Jc', 'Jd', 'Jh', 'Js', 'Kc', 'Kd', 'Kh', 'Ks',
    'Qc', 'Qd', 'Qh', 'Qs'
])}

def visualize_image_with_annotation_bboxes(image_dir, label_dir, n=12):
    image_files = sorted(os.listdir(image_dir))
    sample_files = random.sample(image_files, min(n, len(image_files)))
    fig, axs = plt.subplots(4, 3, figsize=(15, 20))
    for i, image_file in enumerate(sample_files):
        row, col = divmod(i, 3)
        image_path = os.path.join(image_dir, image_file)
        img = cv2.cvtColor(cv2.imread(image_path), cv2.COLOR_BGR2RGB)

        label_path = os.path.join(label_dir, image_file[:-4] + ".txt")
        if not os.path.exists(label_path):
            print(f" No label for {image_file}")
            continue

        with open(label_path) as f:
            for line in f:
                cls, xc, yc, w, h = map(float, line.split())
                H, W, _ = img.shape
                x1, y1 = int((xc - w/2)*W), int((yc - h/2)*H)
                x2, y2 = int((xc + w/2)*W), int((yc + h/2)*H)
                cv2.rectangle(img, (x1, y1), (x2, y2), (0,255,0), 2)
                cv2.putText(img, Idx2Label[int(cls)], (x1, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

        axs[row, col].imshow(img)
        axs[row, col].axis("off")

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    visualize_image_with_annotation_bboxes(
        "/home/elomelo/card_detection/archive/test/images",
        "/home/elomelo/card_detection/archive/test/labels"
    )
