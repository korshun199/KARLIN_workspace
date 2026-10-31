#!/usr/bin/env python3
"""Plot 200 sorted random values against their percentile rank."""

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.ticker import PercentFormatter
import numpy as np
from scipy.interpolate import PchipInterpolator


VALUES = [
    230, 238, 307, 144, 255, 229, 46, 179, 168, 153,
    269, 272, 81, 221, 262, 312, 110, 284, 148, 166,
    247, 270, 108, 260, 71, 72, 268, 137, 241, 273,
    353, 82, 286, 82, 207, 158, 130, 169, 151, 59,
    216, 354, 67, 180, 255, 229, 169, 88, 360, 285,
    158, 116, 214, 63, 177, 253, 293, 169, 270, 232,
    98, 322, 203, 279, 283, 109, 232, 297, 196, 117,
    180, 175, 280, 226, 244, 343, 87, 114, 72, 349,
    76, 320, 110, 126, 64, 224, 160, 152, 256, 310,
    285, 147, 123, 41, 165, 106, 263, 220, 76, 341,
    88, 265, 108, 92, 236, 92, 67, 343, 147, 313,
    163, 114, 274, 300, 347, 58, 269, 330, 154, 246,
    71, 90, 224, 82, 280, 132, 52, 191, 271, 126,
    215, 41, 176, 293, 86, 136, 130, 220, 293, 168,
    78, 161, 40, 174, 52, 245, 173, 46, 66, 189,
    209, 98, 320, 228, 307, 128, 206, 63, 294, 157,
    253, 187, 246, 185, 99, 263, 286, 229, 64, 176,
    269, 285, 151, 138, 296, 181, 152, 81, 184, 123,
    57, 225, 57, 55, 144, 190, 261, 154, 207, 300,
    319, 74, 206, 151, 145, 116, 193, 315, 183, 154,
]
COUNT = len(VALUES)
OUTPUT = Path(__file__).with_name("random_values_percentiles.png")


def main() -> None:
    values = np.sort(np.asarray(VALUES, dtype=float))
    # Percentile positions match NumPy's linear percentile definition.
    percentile_rank = np.linspace(0, 100, COUNT)
    smooth_percentiles = np.linspace(0, 100, 2001)
    smooth_values = PchipInterpolator(percentile_rank, values)(smooth_percentiles)

    median = float(np.percentile(values, 50, method="linear"))
    percentile_90 = float(np.percentile(values, 90, method="linear"))

    color_map = LinearSegmentedColormap.from_list(
        "mint_spectrum",
        ["#f2fff4", "#35f65b", "#00dfa8", "#13aaf2", "#5859e8",
         "#b94bd7", "#f34b83", "#ffad38", "#a81443"],
    )
    normalize = Normalize(vmin=40, vmax=360)

    fig, ax = plt.subplots(figsize=(10, 7), constrained_layout=True)
    fig.patch.set_facecolor("#f3f6fb")
    ax.set_facecolor("#ffffff")
    points = np.column_stack((smooth_values, smooth_percentiles)).reshape(-1, 1, 2)
    segments = np.concatenate((points[:-1], points[1:]), axis=1)
    curve = LineCollection(segments, cmap=color_map, norm=normalize, linewidth=3.5,
                           capstyle="round", zorder=2)
    curve.set_array((smooth_values[:-1] + smooth_values[1:]) / 2)
    ax.add_collection(curve)

    quantiles = [
        (median, 50, "Медиана", "#e28b26"),
        (percentile_90, 90, "90-й перцентиль", "#d44f73"),
    ]
    for x_value, y_percent, label, color in quantiles:
        ax.hlines(y_percent, 40, x_value, color=color, linestyle="--", linewidth=1.7)
        ax.vlines(x_value, 0, y_percent, color=color, linestyle="--", linewidth=1.7)
        ax.scatter([x_value], [y_percent], color=color, edgecolor="white", linewidth=1.2,
                   s=95, zorder=5, label=f"{label}: {x_value:.1f} при {y_percent}%")

    ax.set(
        title=f"{COUNT} отсортированных случайных значений",
        xlabel="Значения (от 40 до 360), по возрастанию",
        ylabel="Процентиль (%)",
        xlim=(40, 360),
        ylim=(0, 100),
    )
    ax.set_xticks(np.arange(40, 361, 40))
    ax.set_yticks(np.arange(0, 101, 10))
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0))
    ax.grid(True, color="#dfe5ef", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#bdc7d8")
    ax.legend(loc="lower right", frameon=True, facecolor="white", edgecolor="#e3e8f0")
    fig.colorbar(curve, ax=ax, label="Значение по оси X")

    fig.savefig(OUTPUT, dpi=180, facecolor=fig.get_facecolor())
    print(f"Медиана: {median:.2f}")
    print(f"90-й перцентиль: {percentile_90:.2f}")
    print(f"График сохранён: {OUTPUT}")


if __name__ == "__main__":
    main()
