
from typing import Iterable
from models import Review

def compute_avg_rating(reviews: Iterable[Review]) -> float:
    """
    Devuelve el promedio de rating (1–5) a partir de una lista de reviews.
    Si no hay reviews, devuelve 0.0.
    """
    reviews = list(reviews)
    if not reviews:
        return 0.0
    return round(sum(r.rating for r in reviews) / len(reviews), 1)

