#!/usr/bin/env python3
"""Create 30-second OpenCV timing charts for good, bad, and very bad cases."""

import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).parent
TEST_SECONDS = 30
FRAME_BUDGET_MS = 1000 / 30
Y_AXIS_MAX_MS = 220


def load_good_sample() -> tuple[np.ndarray, np.ndarray]:
    data = np.genfromtxt(ROOT / "opencv_30s_results.csv", delimiter=",", names=True)
    return data["elapsed_seconds"], data["processing_ms"]


def make_scenario(mean_ms: float, std_ms: float, spike_chance: float,
                  spike_ms: tuple[float, float], seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Simulate sequential frame processing for 30 seconds with repeatable jitter."""
    rng = np.random.default_rng(seed)
    elapsed = 0.0
    timestamps: list[float] = []
    durations: list[float] = []
    while elapsed < TEST_SECONDS:
        duration = max(1.0, float(rng.normal(mean_ms, std_ms)))
        if rng.random() < spike_chance:
            duration += float(rng.uniform(*spike_ms))
        elapsed += duration / 1000
        timestamps.append(elapsed)
        durations.append(duration)
    return np.asarray(timestamps), np.asarray(durations)


def save_csv(path: Path, elapsed: np.ndarray, frame_ms: np.ndarray) -> None:
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["elapsed_seconds", "processing_ms"])
        writer.writerows(zip(elapsed, frame_ms))


def draw_chart(name: str, title: str, subtitle: str,
               elapsed: np.ndarray, frame_ms: np.ndarray) -> None:
    median = float(np.median(frame_ms))
    p90 = float(np.percentile(frame_ms, 90, method="linear"))
    mean = float(frame_ms.mean())
    throughput = len(frame_ms) / elapsed[-1]
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
               label=f"Общая медиана: {median:.1f} мс")
    ax.axhline(p90, color="#d44f73", linestyle="--", linewidth=1.8,
               label=f"P90: {p90:.1f} мс")
    ax.axhline(FRAME_BUDGET_MS, color="#268a65", linestyle=":", linewidth=2,
               label="Предел для 30 FPS: 33,3 мс")
    ax.set(
        title=f"{title}\n{subtitle}",
        xlabel="Время теста (секунды)",
        ylabel="Время обработки одного кадра (мс)",
        xlim=(0, TEST_SECONDS),
        ylim=(0, Y_AXIS_MAX_MS),
    )
    ax.set_xticks(np.arange(0, TEST_SECONDS + 1, 2))
    ax.grid(True, color="#dfe5ef", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#bdc7d8")
    ax.legend(loc="upper right", frameon=True, facecolor="white", edgecolor="#e3e8f0")
    fig.savefig(ROOT / f"opencv_{name}.png", dpi=180, facecolor=fig.get_facecolor())

    print(f"{name}: {len(frame_ms)} кадров за {elapsed[-1]:.2f} с; "
          f"среднее {mean:.1f} мс, медиана {median:.1f} мс, P90 {p90:.1f} мс, "
          f"{throughput:.1f} кадров/с")


def main() -> None:
    scenarios = {
        "good": (
            "Хорошо",
            "Реальный замер OpenCV, Full HD, облачный CPU",
            *load_good_sample(),
        ),
        "bad": (
            "Плохо",
            "Примерный массив: обычные задержки около 40 мс, периодические всплески",
            *make_scenario(40, 8, 0.018, (25, 55), seed=104),
        ),
        "very_bad": (
            "Очень плохо",
            "Примерный массив: около 90 мс на кадр и частые длинные всплески",
            *make_scenario(90, 18, 0.025, (50, 110), seed=205),
        ),
    }

    for name, (title, subtitle, elapsed, frame_ms) in scenarios.items():
        draw_chart(name, title, subtitle, elapsed, frame_ms)
        save_csv(ROOT / f"opencv_{name}_results.csv", elapsed, frame_ms)


if __name__ == "__main__":
    main()
