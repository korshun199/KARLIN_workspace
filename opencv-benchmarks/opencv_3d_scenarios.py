#!/usr/bin/env python3
"""Build matching 3D views for the good, bad, and very bad timing arrays."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import plotly.graph_objects as go
from matplotlib import cm
from matplotlib.colors import Normalize


ROOT = Path(__file__).parent
FRAME_BUDGET_MS = 1000 / 30
TIME_EDGES = np.arange(0, 31, 1)
LATENCY_EDGES = np.arange(0, 201, 5)
Z_MAX = 100
SCENARIOS = {
    "good": ("Хорошо", "Реальный замер OpenCV, Full HD"),
    "bad": ("Плохо", "Примерный массив задержек"),
    "very_bad": ("Очень плохо", "Примерный массив с длинными задержками"),
}


def main() -> None:
    time_centers = (TIME_EDGES[:-1] + TIME_EDGES[1:]) / 2
    latency_centers = (LATENCY_EDGES[:-1] + LATENCY_EDGES[1:]) / 2
    xx, yy = np.meshgrid(time_centers, latency_centers)
    plane_x, plane_z = np.meshgrid([0, 30], [0, Z_MAX])
    plane_y = np.full_like(plane_x, FRAME_BUDGET_MS, dtype=float)

    for key, (title, description) in SCENARIOS.items():
        data = np.genfromtxt(ROOT / f"opencv_{key}_results.csv", delimiter=",", names=True)
        elapsed = np.minimum(data["elapsed_seconds"], 30)
        frame_ms = data["processing_ms"]
        p90 = float(np.percentile(frame_ms, 90, method="linear"))
        p98 = float(np.percentile(frame_ms, 98, method="linear"))
        counts, _, _ = np.histogram2d(
            elapsed, frame_ms, bins=[TIME_EDGES, LATENCY_EDGES]
        )
        frames_per_second = counts.sum(axis=1, keepdims=True)
        frequency_pct = np.divide(
            counts * 100,
            frames_per_second,
            out=np.zeros_like(counts),
            where=frames_per_second > 0,
        )

        figure = go.Figure()
        figure.add_trace(go.Surface(
            x=xx,
            y=yy,
            z=frequency_pct.T,
            colorscale="Viridis",
            cmin=0,
            cmax=Z_MAX,
            colorbar={"title": "Доля кадров (%)"},
            name="Частота кадров",
            hovertemplate=(
                "Секунда: %{x:.0f}<br>Время кадра: %{y:.1f} мс"
                "<br>Доля кадров в секунде: %{z:.1f}%<extra></extra>"
            ),
        ))
        planes = [
            (FRAME_BUDGET_MS, "Предел 30 FPS: 33,3 мс", "#268a65"),
            (p90, f"P90: {p90:.1f} мс", "#e28b26"),
            (p98, f"P98: {p98:.1f} мс", "#d44f73"),
        ]
        for latency_ms, label, color in planes:
            plane_y = np.full_like(plane_x, latency_ms, dtype=float)
            figure.add_trace(go.Surface(
                x=plane_x,
                y=plane_y,
                z=plane_z,
                colorscale=[[0, color], [1, color]],
                opacity=0.055,
                showscale=False,
                showlegend=False,
                name=label,
                hovertemplate=f"{label}<extra></extra>",
            ))
            figure.add_trace(go.Scatter3d(
                x=[0, 30],
                y=[latency_ms, latency_ms],
                z=[0, 0],
                mode="lines",
                line={"color": color, "width": 6, "dash": "dash"},
                name=label,
                hovertemplate=f"{label}<extra></extra>",
            ))
        figure.update_layout(
            title=f"{title}: распределение OpenCV за 30 секунд<br><sup>{description}</sup>",
            scene={
                "xaxis_title": "Время теста (с)",
                "yaxis_title": "Время обработки кадра (мс)",
                "zaxis_title": "Доля кадров в интервале 5 мс за секунду (%)",
                "xaxis": {"range": [0, 30]},
                "yaxis": {"range": [0, 200]},
                "zaxis": {"range": [0, Z_MAX]},
                "camera": {"eye": {"x": 1.65, "y": -1.75, "z": 1.2}},
            },
            margin={"l": 0, "r": 0, "t": 85, "b": 0},
        )
        figure.write_html(ROOT / f"opencv_{key}_3d.html", include_plotlyjs=True, full_html=True)

        fig = plt.figure(figsize=(11, 8), constrained_layout=True)
        ax = fig.add_subplot(111, projection="3d")
        ax.plot_surface(
            xx, yy, frequency_pct.T, cmap=cm.viridis,
            norm=Normalize(vmin=0, vmax=Z_MAX), linewidth=0, antialiased=True,
            alpha=0.95,
        )
        for latency_ms, label, color in planes:
            plane_y = np.full_like(plane_x, latency_ms, dtype=float)
            ax.plot_surface(plane_x, plane_y, plane_z, color=color, alpha=0.045,
                            linewidth=0, shade=False)
            ax.plot([0, 30], [latency_ms] * 2, [0, 0], color=color, linewidth=3,
                    linestyle="--", label=label)
        ax.set(
            title=f"{title}: задержки за 30 секунд\n{description}",
            xlabel="Время теста (с)",
            ylabel="Время кадра (мс)",
            zlabel="Доля кадров за секунду (%)",
            xlim=(0, 30),
            ylim=(0, 200),
            zlim=(0, Z_MAX),
        )
        ax.view_init(elev=28, azim=-58)
        ax.legend(loc="upper left")
        fig.savefig(ROOT / f"opencv_{key}_3d.png", dpi=180, facecolor="#f3f6fb")
        print(f"{title}: P90 {p90:.2f} мс, P98 {p98:.2f} мс; "
              f"созданы opencv_{key}_3d.html и opencv_{key}_3d.png")


if __name__ == "__main__":
    main()
