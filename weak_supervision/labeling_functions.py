# Importation

import pandas as pd
import datetime as dt
import numpy as np
import re
import nltk
nltk.download('wordnet')
from nltk.corpus import wordnet
from snorkel.labeling import LabelingFunction, labeling_function
from snorkel.preprocess import preprocessor
from textblob import TextBlob
import operator as op
from typing import Callable


# Global Variables

ABUSE = 1
NOT_ABUSE = 0
ABSTAIN = -1

lfs = dict()


# NLP Labeling Functions

### Preprocessors
@preprocessor(memoize=True)
def textblob_polarity(x):
    scores = TextBlob(x.text)
    x.polarity = scores.polarity
    return x

@preprocessor(memoize=True)
def textblob_subjectivity(x):
    scores = TextBlob(x.text)
    x.subjectivity = scores.subjectivity
    return x

### NLP labeling functions

def lfg_polarity(op_func: Callable[[float, float], bool],
                bound: float,                  
                CONSTANT: int,
                name: str = 'polarityLabelingFunction',
                ABSTAIN: int = -1
                ):
    def lf_polarity(x):
        return CONSTANT if op_func(x.polarity, bound) else ABSTAIN
    return LabelingFunction(name=name, f=lf_polarity, pre=[textblob_polarity])

def lfg_subjectivity(op_func: Callable[[float, float], bool],
                    bound: float,
                    CONSTANT: int,
                    name: str = 'subjectivityLabelingFunction',
                    ABSTAIN: int = -1,
                    ):
    def lf_subjectivity(x):
        return CONSTANT if op_func(x.subjectivity, bound) else ABSTAIN
    return LabelingFunction(name=name, f=lf_subjectivity, pre=[textblob_subjectivity])





# Heuristic labeling functions

### length labeling function
def lfg_lengthtext(min_characters: int,
                            op_func: Callable[[float, float], bool],
                            CONSTANT: int,
                            name: str = 'lengthtextLabelingFunction',
                            ABSTAIN: int = -1):
    def lf_lengthtext(x):
        return CONSTANT if op_func(len(x.text), min_characters) else ABSTAIN
    return LabelingFunction(name=name, f=lf_lengthtext)

### Keyword labeling function
def lfg_keywords(keywords: list, 
                          CONSTANT: int, 
                          name: str = 'keywordsLabelingFunction',
                          ABSTAIN: int = -1):
    @labeling_function()
    def func(x):
        return CONSTANT if any(word in x.text.lower() for word in keywords) else ABSTAIN
    func.name = name
    return func

### Regex labeling function


def lfg_regex(regex, 
                       CONSTANT: int, 
                       name: str = 'regexLabelingFunction',
                       ABSTAIN: int = -1):
    @labeling_function()
    def func(x):
        return CONSTANT if re.search(regex, x.text.lower(), flags=re.I) else ABSTAIN
    func.name = name
    return func



# Annotators Labeling Functions

def worker_lf(x, worker_dict):
    return worker_dict.get(x.rev_id, ABSTAIN)

def lfg_worker(worker_id, worker_dicts):
    worker_dict = worker_dicts[worker_id]
    name = f"worker_{worker_id}"
    return LabelingFunction(name, f=worker_lf, resources={"worker_dict": worker_dict})



# Helper functions

def load_annotations(path: str) -> pd.DataFrame:
    annotations = pd.read_table(path)
    return annotations

def load_keywords(path: str) -> pd.DataFrame:
    keywords = pd.read_csv(path).keyword.values
    return keywords

def get_worker_dicts(annotations: pd.DataFrame) -> dict:

    labels_by_annotator = annotations.groupby("worker_id")
    worker_dicts = {}
    for worker_id in labels_by_annotator.groups:
        worker_df = labels_by_annotator.get_group(worker_id)[["rev_id", "attack"]]
        worker_dicts[worker_id] = dict(zip(worker_df.rev_id, worker_df.attack))
    return worker_dicts


# Get lfs

def get_lfs(path_keywords: str, path_annotations: str) -> dict:
    lfs = dict()

    lfs['polarity_negative'] = lfg_polarity(op.lt, -0.25, ABUSE, name='polarity_negative')
    lfs['polarity_positive'] = lfg_polarity(op.ge, 0.1, NOT_ABUSE, name='polarity_positive')

    lfs['length_text'] = lfg_lengthtext(9500, op.gt, ABUSE)

    badwords = load_keywords(path_keywords)
    lfs['badwords'] = lfg_keywords(badwords, ABUSE)

    annotations = load_annotations(path_annotations)
    worker_dicts = get_worker_dicts(annotations)
    for worker_id in worker_dicts:
        name = f"worker_{worker_id}"
        lfs[name] = lfg_worker(worker_id, worker_dicts)

    return lfs


# Wordnet expansion

badwords = []
for word in ['bad', 'worst', 'horrible', 'ridiculous', 'appaling', 'long', 'boring', 
             'predictable', 'tiring', 'non-credible']:
    for syn in wordnet.synsets(word):
        for i in syn.lemmas():
             badwords.append(i.name())
                
badwords = [s.lower().replace('_', ' ') for s in np.unique(np.array(badwords))]

goodwords = []
for word in ['good', 'best', 'marvelous', 'incredible', 'mesmerizing', 'entertaining', 
             'unforgettable', 'beautiful', 'cute', 'deep']:
    for syn in wordnet.synsets(word):
        for i in syn.lemmas():
             goodwords.append(i.name())
                
goodwords = [s.lower().replace('_', ' ') for s in np.unique(np.array(goodwords))]



# IMDB specific

def lfg_regex2(keywords, 
               CONSTANT: int, 
               name: str = 'regexLabelingFunction',
               specific_keywords = ['act', 'sound', 'edit', 'direct', 'film', 'picture'],
               ABSTAIN: int = -1):
    
    @labeling_function()
    def func(x):
        for word in specific_keywords:
            for keyword in keywords:
                if re.search(f"({keyword}|{word})"+"\W+(?:\w+\W+){0,2}?"+f"({keyword}|{word})", x.text.lower(), flags=re.I):
                    return CONSTANT 
        return ABSTAIN
    func.name = name
    return func



# for binary_movie sentiment, labels are inverted
def get_lfs_imdb(treshold_abuse: float = -0.05, treshold_notabuse: float = 0., treshold_subjectivity: float = 0.3) -> dict:
    lfs = dict()

    lfs['polarity_negative'] = lfg_polarity(op.lt, treshold_abuse, NOT_ABUSE, name='polarity_negative')
    lfs['polarity_positive'] = lfg_polarity(op.ge, treshold_notabuse, ABUSE, name='polarity_positive')

    lfs['subjectivity'] = lfg_subjectivity(op.lt, treshold_subjectivity, ABUSE, name='subjectivity')

    lfs['badwords'] = lfg_keywords(badwords, NOT_ABUSE, name='badwords')
    lfs['goodwords'] = lfg_keywords(goodwords, ABUSE, name='goodwords')

    lfs['good_acting'] = lfg_regex2(goodwords, NOT_ABUSE, name='good_acting')
    lfs['bad_acting'] = lfg_regex2(badwords, ABUSE, name='bad_acting')

    return lfs