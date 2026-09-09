from typing import List, Tuple, Optional
import math


def intersect_ray_with_rectangle(
    origin: Tuple[float, float],
    direction: Tuple[float, float],
    top: float,
    left: float,
    bottom: float,
    right: float,
) -> Optional[Tuple[float, float]]:
    """
    Intersects a ray with an axis-aligned rectangle.
    """
    EPSILON = 0.00001
    # Parametrize the ray: Ray = ray_origin + t * ray_direction
    t_min = -math.inf
    t_max = math.inf

    # Check intersection with the x boundaries of the rectangle
    if direction[0] != 0:
        t_x_min = (left - origin[0]) / direction[0]
        t_x_max = (right - origin[0]) / direction[0]

        if t_x_min > t_x_max:
            t_x_min, t_x_max = t_x_max, t_x_min

        t_min = max(t_min, t_x_min)
        t_max = min(t_max, t_x_max)
    elif not (left <= origin[0] <= right):
        # If the ray is parallel to the x-axis but not within the rectangle's x bounds
        return None

    # Check intersection with the y boundaries of the rectangle
    if direction[1] != 0:
        t_y_min = (top - origin[1]) / direction[1]
        t_y_max = (bottom - origin[1]) / direction[1]

        if t_y_min > t_y_max:
            t_y_min, t_y_max = t_y_max, t_y_min

        t_min = max(t_min, t_y_min)
        t_max = min(t_max, t_y_max)
    elif not (top <= origin[1] <= bottom):
        # If the ray is parallel to the y-axis but not within the rectangle's y bounds
        return None

    # Check if the ray actually intersects the rectangle
    if t_min > t_max or t_max < 0:
        return None

    # Calculate the intersection point using the valid t_min
    intersection_point = (
        origin[0] + t_min * direction[0],
        origin[1] + t_min * direction[1],
    )

    # Check if the intersection point is within the rectangle's boundaries
    if (
        left - EPSILON <= intersection_point[0] <= right
        and top - EPSILON <= intersection_point[1] <= bottom
    ):
        return intersection_point
    return None


def line_intersection(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    q1: Tuple[float, float],
    q2: Tuple[float, float],
) -> Tuple[float, float] | None:
    """
    Helper function to compute the intersection of two line segments (p1-p2 and q1-q2).
    Returns the intersection point or None if no intersection.
    """
    dx1, dy1 = p2[0] - p1[0], p2[1] - p1[1]
    dx2, dy2 = q2[0] - q1[0], q2[1] - q1[1]

    det = dx1 * dy2 - dy1 * dx2
    if abs(det) < 1e-10:  # Parallel lines
        return None

    # Parametric intersection calculation
    t = ((q1[0] - p1[0]) * dy2 - (q1[1] - p1[1]) * dx2) / det
    u = ((q1[0] - p1[0]) * dy1 - (q1[1] - p1[1]) * dx1) / det

    if (
        t >= 0 and 0 <= u <= 1
    ):  # t >= 0 ensures the intersection is along the ray
        x = p1[0] + t * dx1
        y = p1[1] + t * dy1
        return x, y

    return None


def distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    x1, y1 = p1
    x2, y2 = p2
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx * dx + dy * dy)


def intersect_ray_with_polygon(
    origin: Tuple[float, float],
    direction: Tuple[float, float],
    vertices: List[Tuple[float, float]],
) -> Tuple[float, float] | None:
    closest_point = None
    min_distance = float("inf")

    # Define the ray's endpoint far in the direction
    ray_end = (origin[0] + direction[0] * 1e6, origin[1] + direction[1] * 1e6)

    # Iterate over all edges of the polygon defined by vertices
    for i in range(len(vertices)):
        p1 = vertices[i]
        p2 = vertices[
            (i + 1) % len(vertices)
        ]  # Wrap around to the first vertex

        intersection = line_intersection(origin, ray_end, p1, p2)
        if intersection:
            d = distance(intersection, origin)
            if d < min_distance:
                closest_point = intersection
                min_distance = d

    return closest_point

def intersect_line_with_rect(
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    rect: Tuple[float, float, float, float],  # (left, top, right, bottom)
) -> Tuple[float, float] | None:
    left, top, right, bottom = rect
    edges = [
        ((left, top), (right, top)),
        ((right, top), (right, bottom)),
        ((right, bottom), (left, bottom)),
        ((left, bottom), (left, top)),
    ]
    for edge_start, edge_end in edges:
        intersection = line_intersection(p1, p2, edge_start, edge_end)
        if intersection:
            return intersection
    return None

from qtpy.QtCore import QLineF, QPointF


def distance_to_segment(line: QLineF, point: QPointF) -> float:
    dx = line.x2() - line.x1()
    dy = line.y2() - line.y1()

    if dx == 0 and dy == 0:
        return QLineF(point, line.p1()).length()

    t = (
        (point.x() - line.x1()) * dx
        + (point.y() - line.y1()) * dy
    ) / (dx * dx + dy * dy)

    t = max(0.0, min(1.0, t))

    closest = QPointF(
        line.x1() + t * dx,
        line.y1() + t * dy,
    )

    return QLineF(point, closest).length()


from qtpy.QtGui import *
from qtpy.QtCore import *
from qtpy.QtWidgets import *



def intersect_line_with_path(
    p1: QPointF, 
    p2: QPointF, 
    path: QPainterPath,
    tolerance: float = 1.0
) -> QPointF|None:
    """
    Finds the intersection point of a line segment (ray) defined by p1 and p2 with a given QPainterPath.
    Uses an optimized approach with configurable tolerance for better performance and accuracy.
    
    Args:
        p1: Start point of the ray
        p2: End point of the ray
        path: QPainterPath to intersect with
        tolerance: Thickness of the stroke used for intersection detection (default: 1.0)
    
    Returns:
        The intersection point as QPointF or None if no intersection is found
    
    Notes:
        - Uses vector math to ensure accurate direction checking
        - Handles edge cases like parallel lines and tangent intersections
        - Optimized to minimize unnecessary path operations
    """
    # Early exit if either point is null or path is empty
    if not p1 or not p2 or path.isEmpty():
        return None
    
    # Calculate ray vector and length
    ray_vector = QPointF(p2.x() - p1.x(), p2.y() - p1.y())
    ray_length = (ray_vector.x() ** 2 + ray_vector.y() ** 2) ** 0.5
    
    if ray_length < 1e-6:  # Protect against zero-length rays
        return None
    
    # Normalize ray vector for direction checks
    ray_unit = QPointF(ray_vector.x() / ray_length, ray_vector.y() / ray_length)
    
    # Create and prepare the ray path
    ray_path = QPainterPath()
    ray_path.moveTo(p1)
    ray_path.lineTo(p2)
    
    # Add thickness to the paths with specified tolerance
    stroker = QPainterPathStroker()
    stroker.setWidth(tolerance)
    stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    
    # Create stroked paths
    stroked_ray = stroker.createStroke(ray_path)
    
    # Find intersection
    intersection = stroked_ray.intersected(path)
    
    if intersection.isEmpty():
        return None
    
    def calculate_point_projection(point: QPointF) -> float:
        """Calculate the projection of a point onto the ray direction."""
        dx = point.x() - p1.x()
        dy = point.y() - p1.y()
        return dx * ray_unit.x() + dy * ray_unit.y()
    
    # Get all intersection points and find the closest valid one
    best_point = None
    min_projection = float('inf')
    
    for i in range(intersection.elementCount()):
        element = intersection.elementAt(i)
        if element.type == QPainterPath.ElementType.MoveToElement:
            point = QPointF(element.x, element.y)
            projection = calculate_point_projection(point)
            
            # Check if point is in forward direction and closer than current best
            if 0 <= projection <= ray_length and projection < min_projection:
                best_point = point
                min_projection = projection
    
    return best_point


def getShapeRight(shape:QGraphicsItem | QPainterPath | QRectF | QPointF)->QPointF:
    """return scene position"""
    match shape:
        case QGraphicsItem():
            return shape.mapToScene(QPointF(shape.boundingRect().right(), shape.boundingRect().center().y()))
        case QPainterPath():
            rect = shape.boundingRect()
            return QPointF(rect.right(), rect.center().y())
        case QRectF():
            return QPointF(shape.right(), shape.center().y())
        case QPointF():
            return shape
        case _:
            raise ValueError()


def getShapeLeft(shape:QGraphicsItem | QPainterPath | QRectF | QPointF)->QPointF:
    match shape:
        case QGraphicsItem():
            return shape.mapToScene(QPointF(shape.boundingRect().left(), shape.boundingRect().center().y()))#+QPointF(shape.boundingRect().right(), 0)
        case QPainterPath():
            rect = shape.boundingRect()
            return QPointF(rect.left(), rect.center().y())
        case QRectF():
            return QPointF(shape.left(), shape.center().y())
        case QPointF():
            return shape
        case _:
            raise ValueError()


def getShapeCenter(shape: QPointF | QRectF | QPainterPath | QGraphicsItem)->QPointF:
    """
    Get the center point in scene coordinates of a shape, 
    which can be a QPointF, QRectF, QPainterPath, or QGraphicsItem.
    """
    match shape:
        case QPointF() | QPoint():
            return QPointF(shape)
        case QRectF() | QRect():
            return QPointF(shape.center())
        case QPainterPath():
            return shape.boundingRect().center()
        case QGraphicsItem():
            sceneShape = shape.sceneTransform().map(shape.shape())
            return sceneShape.boundingRect().center()
        case _:
            raise ValueError(f"Unsupported shape type for getting center point. got: {shape}")


def makeLineToShape(
    origin: QPointF, shape: QPointF | QRectF | QPainterPath | QGraphicsItem
)->QLineF:
    """
    Make a line - in scene coordinates - from the origin to the center of the shape.
    The line will intersect the shape at its center or closest point.
    """

    center = getShapeCenter(shape)
    match shape:
        case QPointF()|QPoint():
            intersection = QPointF(center)

        case QRectF() | QRect():
            rect = shape
            V = center - origin
            if xy := intersect_ray_with_rectangle(
                origin=(origin.x(), origin.y()),
                direction=(V.x(), V.y()),
                top=rect.top(),
                left=rect.left(),
                bottom=rect.bottom(),
                right=rect.right(),
            ):
                intersection = QPointF(*xy)
            else:
                intersection = QPointF(center)

        case QPainterPath():
            if P := intersect_line_with_path(
                origin, center, shape
            ):  # TODO: use intersect_ray_with_polygon
                intersection = P
            else:
                intersection = center
                
        case QGraphicsItem():
            sceneShape = shape.sceneTransform().map(shape.shape())
            if P := intersect_line_with_path(
                origin, center, sceneShape
            ):  # TODO: use intersect_ray_with_polygon
                intersection = P
            else:
                intersection = center
        case _:
            raise ValueError

    return QLineF(origin, intersection)


def makeLineBetweenShapes(
    A: QPointF | QRectF | QPainterPath | QGraphicsItem,
    B: QPointF | QRectF | QPainterPath | QGraphicsItem,
    distance:float=10
) -> QLineF:
    """
    Make a line (in scene coordinates) between two shapes, offset by a specified distance.
    The line will be adjusted to avoid overlap and ensure a clear connection.
    """
    
    Ac = getShapeCenter(A)
    Bc = getShapeCenter(B)

    I2 = makeLineToShape(Ac, B).p2()
    I1 = makeLineToShape(Bc, A).p2()

    line = QLineF(I1, I2)
    length = line.length()
    if length <= 0.0001:
        # If the length is too small, return a zero-length line
        return QLineF(I1, I1)
    line.setP1(line.pointAt(distance/length))

    line.setLength(length-distance*2)

    return line

def makeArrowShape(line:QLineF, width=1.0):
    # arrow shape
    head_width, head_length = width*2, width*4
    # create an arrow on X+ axis with line length

    vertices = [
        (0, -width/2),
        (line.length()-head_length, -width/2),
        (line.length()-head_length, -head_width),
        (line.length(), 0),
        (line.length()-head_length, +head_width),
        (line.length()-head_length, +width/2),
        (0, +width/2),
        (0, -width/2)
    ]

    arrow_polygon = QPolygonF([QPointF(x, y) for x, y in vertices])
    transform = QTransform()
    transform.translate(line.p1().x(), line.p1().y())
    transform.rotate(-line.angle())

    path = QPainterPath()
    path.addPolygon(transform.map(arrow_polygon))

    return path

from typing import Tuple
import math

def makeHorizontalRoundedPath(line: QLineF):
    """Creates a rounded path between two points with automatic radius adjustment.
    
    Args:
        line: QLineF defining start and end points
        direction: Layout direction (default: LeftToRight)
    
    Returns:
        QPainterPath: A path with rounded corners connecting the points
    """
    A, B = line.p1(), line.p2()
    dx = B.x() - A.x()
    dy = B.y() - A.y()
    
    path = QPainterPath()
    path.moveTo(A)
    
    # Base radius with constraints
    r = 27
    is_leftward = dx < 0
    
    if is_leftward:
        r1 = min(r, min(abs(dx/4), abs(dy/4)))
        r2 = min(abs(dx), abs(dy) - r1 * 3)
    else:
        r1 = min(r, min(abs(dx/2), abs(dy/2)))
        r2 = min(abs(dx), abs(dy)) - r1
    
    # Define arc parameters based on direction
    if is_leftward:
        create_leftward_path(path, A, B, r1, r2, dy > 0)
    else:
        create_rightward_path(path, A, B, r1, r2, dy > 0)
    
    path.lineTo(B)
    return path


def create_leftward_path(path: QPainterPath, A: QPointF, B: QPointF, r1: float, r2: float, is_downward: bool):
    """Creates the path segments for leftward movement."""
    if is_downward:
        path.arcTo(A.x() - r1, A.y(), r1 * 2, r1 * 2, 90, -180)
        path.arcTo(B.x() - r1, A.y() + r2 * 2 + r1 * 2, r2 * 2, -r2 * 2, -90, -90)
        path.arcTo(B.x() + r1, B.y() - r1 * 2, -r1 * 2, r1 * 2, 0, -90)
    else:
        path.arcTo(A.x() - r1, A.y(), r1 * 2, -r1 * 2, 90, -180)
        path.arcTo(B.x() - r1, A.y() - r2 * 2 - r1 * 2, r2 * 2, r2 * 2, -90, -90)
        path.arcTo(B.x() + r1, B.y() + r1 * 2, -r1 * 2, -r1 * 2, 0, -90)


def create_rightward_path(path: QPainterPath, A: QPointF, B: QPointF, r1: float, r2: float, is_downward: bool):
    """Creates the path segments for rightward movement."""
    if is_downward:
        path.arcTo(A.x() - r1, A.y(), r1 * 2, r1 * 2, 90, -90)
        path.arcTo(A.x() + r1, B.y() - r2 * 2, r2 * 2, r2 * 2, 180, 90)
    else:
        path.arcTo(A.x() - r1, A.y(), r1 * 2, -r1 * 2, 90, -90)
        path.arcTo(A.x() + r1, B.y() + r2 * 2, r2 * 2, -r2 * 2, 180, 90)


def makeVerticalRoundedPath(line: QLineF, width=1.0, r=27)->QPainterPath:
    """Creates a rounded path between two points with automatic radius adjustment.
    
    Args:
        line: QLineF defining start and end points
        direction: Layout direction (default: TopToBottom)
    
    Returns:
        QPainterPath: A path with rounded corners connecting the points
    """
    A, B = line.p1(), line.p2()
    dx = B.x() - A.x()
    dy = B.y() - A.y()
    
    path = QPainterPath()
    path.moveTo(A)
    
    # Base radius with constraints
    is_upward = dy < 0
    
    if is_upward:
        r1 = min(r, min(abs(dy/4), abs(dx/4)))
        r2 = min(abs(dy), abs(dx) - r1 * 3)
    else:
        r1 = min(r, min(abs(dy/2), abs(dx/2)))
        r2 = min(abs(dy), abs(dx)) - r1
    
    # Define arc parameters based on direction
    if is_upward:
        create_upward_path(path, A, B, r1, r2, dx > 0)
    else:
        create_downward_path(path, A, B, r1, r2, dx > 0)
    
    path.lineTo(B)
    return path


def create_downward_path(path: QPainterPath, A: QPointF, B: QPointF, r1: float, r2: float, is_rightward: bool):
    """Creates the path segments for downward movement."""
    if is_rightward:
        path.arcTo(A.x(), A.y() - r1, r1 * 2, r1 * 2, 180, 90)
        path.arcTo(B.x()-r2*2,  A.y() + r1, r2 * 2, r2 * 2, 90, -90)
    else:
        path.arcTo(A.x(), A.y() - r1, -r1 * 2, r1 * 2, 180, 90)
        path.arcTo(B.x() + r2 * 2, A.y() + r1, -r2 * 2, r2 * 2, 90, -90)


def create_upward_path(path: QPainterPath, A: QPointF, B: QPointF, r1: float, r2: float, is_rightward: bool):
    """Creates the path segments for upward movement."""
    if is_rightward:
        path.arcTo(A.x(), A.y() - r1, r1 * 2, r1 * 2, 180, 180)
        path.arcTo(A.x() + r2 * 2 + r1 * 2, B.y() - r1, -r2 * 2, r2 * 2, 0, 90)
        path.arcTo(B.x() - r1 * 2, B.y() + r1, r1 * 2, -r1 * 2, 270, 90)
    else:
        path.arcTo(A.x(), A.y() - r1, -r1 * 2, r1 * 2, 180, 180)
        path.arcTo(A.x() - r2 * 2 - r1 * 2, B.y() - r1, r2 * 2, r2 * 2, 0, 90)
        path.arcTo(B.x() + r1 * 2, B.y() + r1, -r1 * 2, -r1 * 2, 270, 90)