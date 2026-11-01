#!/usr/bin/env python3
"""Measure a small Full HD OpenCV image pipeline for 30 seconds."""

from __future__ import annotations

import csv
import platform
import time
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np


TEST_SECONDS = 30
WIDTH = 1920
HEIGHT = 1080
OUTPUT = Path(__file__).with_name("opencv_30s_benchmark.png")
CSV_OUTPUT = Path(__file__).with_name("opencv_30s_results.csv")


def main() -> None:
    cv2.setUseOptimized(True)
    rng = np.random.default_rng(20261031)
    frame = rng.integers(0, 256, size=(HEIGHT, WIDTH, 3), dtype=np.uint8)

    def process(image: np.ndarray) -> None:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        cv2.Canny(blurred, 75, 150)

    # Warm up OpenCV before starting the timed interval.
    for _ in range(20):
        process(frame)

    samples: list[tuple[float, float]] = []
    start = time.perf_counter()
    while True:
        frame_start = time.perf_counter()
        process(frame)
        frame_end = time.perf_counter()
        samples.append((frame_end - start, (frame_end - frame_start) * 1000))
        if frame_end - start >= TEST_SECONDS:
            break

    elapsed = np.asarray([sample[0] for sample in samples])
    frame_ms = np.asarray([sample[1] for sample in samples])
    median = float(np.median(frame_ms))
    p90 = float(np.percentile(frame_ms, 90, method="linear"))
    mean = float(frame_ms.mean())
    throughput = len(samples) / elapsed[-1]

    with CSV_OUTPUT.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["elapsed_seconds", "processing_ms"])
        writer.writerows(samples)

    fig, ax = plt.subplots(figsize=(11, 6.5), constrained_layout=True)
    fig.patch.set_facecolor("#f3f6fb")
    ax.set_facecolor("#ffffff")
    ax.plot(elapsed, frame_ms, color="#91a8c2", linewidth=0.7, alpha=0.55,
            label="Время на каждый кадр")

    second_bins = np.floor(elapsed).astype(int)
    bin_seconds = np.unique(second_bins)
    per_second_median = np.asarray([
        np.median(frame_ms[second_bins == second]) for second in bin_seconds
    ])
    ax.plot(bin_seconds + 0.5, per_second_median, color="#295da8", linewidth=2.4,
            marker="o", markersize=3.5, label="Медиана за каждую секунду")

    ax.axhline(median, color="#e28b26", linestyle="--", linewidth=1.8,
               label=f"Общая медиана: {median:.2f} мс")
    ax.axhline(p90, color="#d44f73", linestyle="--", linewidth=1.8,
               label=f"P90: {p90:.2f} мс")
    ax.axhline(1000 / 30, color="#268a65", linestyle=":", linewidth=2,
               label="Бюджет кадра для 30 FPS: 33,3 мс")
    ax.set(
        title="OpenCV: обработка Full HD кадров в течение 30 секунд",
        xlabel="Время теста (секунды)",
        ylabel="Время обработки одного кадра (мс)",
        xlim=(0, TEST_SECONDS),
        ylim=(0, None),
    )
    ax.set_xticks(np.arange(0, TEST_SECONDS + 1, 2))
    ax.grid(True, color="#dfe5ef", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#bdc7d8")
    ax.legend(loc="upper right", frameon=True, facecolor="white", edgecolor="#e3e8f0")
    fig.savefig(OUTPUT, dpi=180, facecolor=fig.get_facecolor())

    cpu_model = platform.processor() or platform.machine()
    print(f"OpenCV: {cv2.__version__}")
    print(f"CPU: {cpu_model}; OpenCV threads: {cv2.getNumThreads()}")
    print(f"Кадр: {WIDTH}×{HEIGHT}; тест: {elapsed[-1]:.2f} с; обработано: {len(samples)} кадров")
    print(f"Среднее: {mean:.2f} мс; медиана: {median:.2f} мс; P90: {p90:.2f} мс")
    print(f"Пропускная способность: {throughput:.2f} кадров/с")
    print(f"График: {OUTPUT}")
    print(f"Замеры CSV: {CSV_OUTPUT}")


if __name__ == "__main__":
    main()
