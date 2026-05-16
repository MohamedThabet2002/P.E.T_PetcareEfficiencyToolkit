"""
Charts module for the PET Application.
Provides reusable wrappers for Bar, Pie, and Line charts using PySide6.QtCharts.
"""

from typing import Optional, List, Tuple, Dict, Any

from PyQt5.QtChart import (
    QChartView, QChart, QBarSeries, QBarSet, QBarCategoryAxis,
    QValueAxis, QPieSeries, QLineSeries, QStackedBarSeries, QSplineSeries
)
from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, pyqtProperty
from PyQt5.QtGui import QPainter, QColor, QBrush, QPen

from src.ui.themes.color_palettes import get_active_palette, ThemeConfig

def _get_nice_axis_params(min_val: float = 0, max_val: float = 0) -> Tuple[float, float, int]:
    """Calculates nice min/max and tick count for Y-axis with optional negative values."""
    if max_val < 0:
        max_val = 0
    if min_val > 0:
        min_val = 0
    
    if max_val == 0 and min_val == 0:
        return 0.0, 10.0, 6  # Default 0-10 with steps of 2
    
    # Find the overall range magnitude
    range_max = max(abs(min_val) if min_val != 0 else 0, abs(max_val) if max_val != 0 else 0)
    if range_max <= 0:
        return 0.0, 10.0, 6
    
    # Possible step sizes focusing on 1, 2, 5, 10 patterns
    steps = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000]
    
    # Aim for ~5-6 intervals for clarity
    target_intervals = 6
    raw_step = range_max / target_intervals if target_intervals > 0 else range_max
    
    # Find the smallest step >= raw_step
    actual_step = steps[-1]
    for s in steps:
        if s >= raw_step:
            actual_step = s
            break
    
    # Calculate nice bounds
    if min_val < 0:
        nice_min = -float((int(abs(min_val) / actual_step) + 1) * actual_step)
    else:
        nice_min = 0.0
    
    if max_val > 0:
        nice_max = float((int(max_val / actual_step) + 1) * actual_step)
    else:
        nice_max = 0.0
    
    # Ensure we cover the actual range
    if min_val < nice_min:
        nice_min = -float((int(abs(min_val) / actual_step) + 2) * actual_step)
    if max_val > nice_max:
        nice_max = float((int(max_val / actual_step) + 2) * actual_step)
    
    # Make symmetric if we have both positive and negative
    if min_val < 0 and max_val > 0:
        max_range = max(abs(nice_min), nice_max)
        nice_min = -max_range
        nice_max = max_range
    
    tick_count = int((nice_max - nice_min) / actual_step) + 1
    if tick_count < 3:
        tick_count = 5
    if tick_count > 11:
        tick_count = 6
    
    return nice_min, nice_max, tick_count

class BaseChart(QChartView):
    """Base class for consistent chart styling and rendering."""
    def __init__(self, chart: QChart, palette: ThemeConfig, animated: bool = True, parent: Optional[QWidget] = None):
        super().__init__(chart, parent)
        self._palette = palette # Store the palette
        # Enable high-quality rendering for smoother lines and text
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.TextAntialiasing)
        
        if animated:
            chart.setAnimationOptions(QChart.SeriesAnimations)
        self._text_color = self._palette.qcolor("text_primary")
        self._grid_color = self._palette.qcolor("border")
        self._update_colors()
        
    @pyqtProperty(QColor)
    def textColor(self):
        return self._text_color
    
    @textColor.setter
    def textColor(self, color):
        self._text_color = color
        self._update_colors()
    
    @pyqtProperty(QColor)
    def gridColor(self):
        return self._grid_color
    
    @gridColor.setter
    def gridColor(self, color):
        self._grid_color = color
        self._update_colors()
    
    def _update_colors(self):
        chart = self.chart()
        if not chart: return
        
        brush = QBrush(self._text_color)
        chart.setTitleBrush(brush)
        chart.setBackgroundVisible(False)  # Let the UI theme handle the container background
        
        if chart.legend():
            chart.legend().setLabelColor(self._text_color)
            
        grid_pen = QPen(self._grid_color)
        for axis in chart.axes():
            axis.setLabelsBrush(brush)
            axis.setTitleBrush(brush)
            axis.setLinePen(grid_pen)
            axis.setGridLinePen(grid_pen)
            
        for series in chart.series():
            if isinstance(series, QPieSeries):
                # For Pie charts, need to re-set slice colors if they are theme-dependent
                # This might require a more sophisticated color mapping in color_palettes.py
                chart_colors = [
                    self._palette.get(f"chart_color_{i+1}", "#CCCCCC") for i in range(len(series.slices()))
                ]
                for i, slice_ in enumerate(series.slices()):
                    slice_.setLabelColor(self._text_color)
                    slice_.setBrush(QBrush(QColor(chart_colors[i % len(chart_colors)]))) # Cycle through colors
            # Bar and Line series colors are set during construction
            elif isinstance(series, (QBarSeries, QStackedBarSeries, QLineSeries)):
                pass

# ---------------- BAR CHART ----------------
class BarChart(BaseChart):
    """
    A Bar Chart implementation where each data point is represented as a distinct bar set.
    """
    def __init__(   self, 
                    x_labels: Optional[List[str]] = None,
                    y_values: Optional[List[float]] = None,
                    title: str = "Bar Chart",
                    series_name: str = "Quantity",
                    animated: bool = True, 
                    parent: Optional[QWidget] = None,
                    rotate_x_labels: bool = False,
                    use_palette: bool = True, # Enable individual bar coloring by default
                    palette: ThemeConfig = None # Added palette parameter
                    ):
        chart = QChart()
        chart.setTitle(title)
        
        # Ensure palette is available, fallback to active if not passed
        if palette is None:
            palette = get_active_palette()

        # Define a list of chart colors from the palette for cycling
        chart_colors = [
            palette["chart_color_1"], palette["chart_color_2"],
            palette["chart_color_3"], palette["chart_color_4"],
            palette["chart_color_5"], palette["chart_color_6"],
        ]

        if use_palette and x_labels and y_values:
            series = QStackedBarSeries()
            for i, label in enumerate(x_labels):
                bar_set = QBarSet(label)
                for j in range(len(x_labels)):
                    bar_set << (y_values[i] if i == j else 0)
                series.append(bar_set)
        else:
            # For a single series, use the first chart color
            series = QBarSeries()
            bar_set = QBarSet(series_name)
            if y_values:
                for qty in y_values:
                    bar_set << qty
            series.append(bar_set)

        chart.addSeries(series)
        chart.legend().setVisible(False)
        
        axisX = QBarCategoryAxis()
        axisX.append(x_labels or [])
        # Rotate labels only if explicitly requested (e.g., for time-series with many labels)
        if rotate_x_labels and x_labels:
            axisX.setLabelsAngle(-90)
        chart.addAxis(axisX, Qt.AlignBottom)
        series.attachAxis(axisX)
        
        axisY = QValueAxis()
        axisY.setTitleText(series_name)
        axisY.setLabelFormat("%d")
        
        if y_values:
            y_min = min(y_values)
            y_max = max(y_values)
        else:
            y_min = 0.0
            y_max = 10.0
        nice_min, nice_max, ticks = _get_nice_axis_params(y_min, y_max)
        axisY.setRange(nice_min, nice_max)
        axisY.setTickCount(ticks)
        
        chart.addAxis(axisY, Qt.AlignLeft)
        series.attachAxis(axisY)
        
        # Set colors for the series after it's added to the chart
        if use_palette and x_labels and y_values:
            for i, bar_set in enumerate(series.barSets()):
                bar_set.setColor(QColor(chart_colors[i % len(chart_colors)]))
        elif not use_palette and series.barSets():
            series.barSets()[0].setColor(QColor(chart_colors[0]))
        super().__init__(chart, palette, animated, parent)

# ---------------- PIE CHART ----------------
class PieChart(BaseChart):
    """
    A Pie Chart implementation for displaying proportional data.
    """
    def __init__(   self, 
                    data: Optional[Dict[str, float]] = None, 
                    title: str = "Pie Chart", 
                    animated: bool = True, 
                    parent: Optional[QWidget] = None,
                    palette: ThemeConfig = None, # Added palette parameter
                    hole_size: Optional[float] = None # 0-1 -> renders a donut
                    ):
        series = QPieSeries()
        values = data if data is not None else {"Dogs": 40, "Cats": 30, "Birds": 20, "Other": 10}
        
        # Ensure palette is available, fallback to active if not passed
        if palette is None:
            palette = get_active_palette()

        # Define a list of chart colors from the palette for cycling
        chart_colors = [
            palette["chart_color_1"], palette["chart_color_2"],
            palette["chart_color_3"], palette["chart_color_4"],
            palette["chart_color_5"], palette["chart_color_6"],
        ]

        for k, v in values.items():
            series.append(k, v)
        if hole_size:
            series.setHoleSize(hole_size)
        chart = QChart()
        chart.addSeries(series)
        chart.setTitle(title)
        super().__init__(chart, palette, animated, parent)

# ---------------- LINE CHART ----------------
class LineChart(BaseChart):
    """
    A multi-series Line Chart implementation.
    
    Args:
        series_data: List of tuples (x_values, y_values, series_name)
        x_axis_labels: Categorical labels for the X axis
        y_axis_range: Tuple of (min, max) for the Y axis
    """
    def __init__(   self, 
                    series_data: Optional[List[Tuple[List[float], List[float], str, Optional[str]]]] = None,
                    title: str = "Line Chart", 
                    animated: bool = True, 
                    parent: Optional[QWidget] = None,
                    x_axis_labels: Optional[List[str]] = None,
                    y_axis_range: Optional[Tuple[float, float]] = None,
                    line_width: int = 3,
                    palette: ThemeConfig = None # Added palette parameter
    ):
        # Store parameters for potential re-instantiation or access from dashboard
        self.series_data = series_data
        self.title = title
        self.x_axis_labels = x_axis_labels
        self.y_axis_range = y_axis_range
        self.line_width = line_width
        self.palette = palette if palette else get_active_palette()

        chart = QChart()
        chart.setTitle(title)
        self.chart_font= chart.titleFont()
        self.chart_font.setBold(True)
        self.chart_font.setPointSize(12)
        chart.setTitleFont(self.chart_font)
        
        if series_data:
            for entry in series_data:
                x_values, y_values, name = entry[:3]
                color = entry[3] if len(entry) > 3 else None
                
                series = self._create_series()
                series.setName(name)
                for x, y in zip(x_values, y_values):
                    series.append(x, y)
                chart.addSeries(series)
                
                # Customize the pen for thickness and smoother rendering
                pen = series.pen()
                pen.setWidth(line_width)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                if color:
                    pen.setColor(QColor(color))
                series.setPen(pen)
        
        self._setup_axes(chart, self.x_axis_labels, self.y_axis_range)
        super().__init__(chart, self.palette, animated, parent)

    def _create_series(self):
        """Factory method for creating the series object. Overridden in SplineChart."""
        return QLineSeries()
    
    def _setup_axes(self, chart: QChart, x_axis_labels: Optional[List[str]], y_axis_range: Optional[Tuple[float, float]]):
        """Configures axes for the line chart."""
        if x_axis_labels:
            axisX = QBarCategoryAxis()
            axisX.append(x_axis_labels)
            # Month period (30 labels) is too crowded horizontally; rotation fixes the visibility
            if len(x_axis_labels) > 10:
                axisX.setLabelsAngle(-90)
            chart.addAxis(axisX, Qt.AlignBottom)
            for series in chart.series():
                series.attachAxis(axisX)
        
        if y_axis_range:
            min_r = y_axis_range[0] if len(y_axis_range) > 0 else 0
            max_r = y_axis_range[1] if len(y_axis_range) > 1 else 0
            # If only one value provided, try to infer
            nice_min, nice_max, ticks = _get_nice_axis_params(min_r, max_r)
            axisY = QValueAxis()
            axisY.setRange(nice_min, nice_max)
            axisY.setTickCount(ticks)
            chart.addAxis(axisY, Qt.AlignLeft)
            for series in chart.series():
                series.attachAxis(axisY)

class SplineChart(LineChart):
    """
    A multi-series Spline Chart implementation for smoother curved lines.
    """
    def _create_series(self):
        return QSplineSeries()
