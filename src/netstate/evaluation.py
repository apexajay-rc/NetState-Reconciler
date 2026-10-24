"""Labelled-corpus metrics for measuring drift detector false positives/negatives."""
from dataclasses import dataclass, asdict
@dataclass
class ConfusionMetrics:
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    @property
    def precision(self): return self.true_positive / (self.true_positive + self.false_positive) if self.true_positive + self.false_positive else 1.0
    @property
    def recall(self): return self.true_positive / (self.true_positive + self.false_negative) if self.true_positive + self.false_negative else 1.0
    @property
    def false_positive_rate(self): return self.false_positive / (self.false_positive + self.true_negative) if self.false_positive + self.true_negative else 0.0
    @property
    def false_negative_rate(self): return self.false_negative / (self.false_negative + self.true_positive) if self.false_negative + self.true_positive else 0.0
    def to_dict(self): return {**asdict(self), "precision": self.precision, "recall": self.recall,
                               "false_positive_rate": self.false_positive_rate, "false_negative_rate": self.false_negative_rate}

def measure(labels: list[bool], predictions: list[bool]) -> ConfusionMetrics:
    if len(labels) != len(predictions): raise ValueError("labels and predictions must have equal length")
    tp=sum(y and p for y,p in zip(labels,predictions)); fp=sum((not y) and p for y,p in zip(labels,predictions))
    tn=sum((not y) and (not p) for y,p in zip(labels,predictions)); fn=sum(y and (not p) for y,p in zip(labels,predictions))
    return ConfusionMetrics(tp,fp,tn,fn)
