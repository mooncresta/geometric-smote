"""
This module contains classes to compare and evaluate 
the performance of various oversampling algorithms.
"""

# Author: Georgios Douzas <gdouzas@icloud.com>

import pandas as pd
from os import listdir, chdir
from re import match, sub
from sklearn.model_selection import StratifiedKFold
from imblearn.pipeline import make_pipeline
from sklearn.model_selection import cross_val_score
from sklearn.metrics import roc_auc_score, f1_score
from imblearn.metrics import geometric_mean_score
from sklearn.metrics import make_scorer
from scipy.stats import friedmanchisquare


def count_elements(elements):
    """Returns a list with modified elements by a count index."""
    elements_map = {}
    elements_modified = []
    for element in elements:
        if element in elements_map.keys():
            elements_map[element] += 1
            elements_modified.append(element + str(elements_map[element]))
        else:
            elements_map[element] = 1
            elements_modified.append(element)
    return elements_modified

def extract_pvalue(dataframe):
    """Extracts p-values applying the Friedman test to measurements."""
    measurements = []
    for col in dataframe.columns[2:]:
        measurements.append(dataframe[col])
    return friedmanchisquare(*measurements).pvalue


class BinaryExperiment:
    """Class for comparison of oversampling algorithms performance 
    on imbalanced binary classification problems."""

    def __init__(self, 
        oversampling_methods, 
        classifiers,
        datasets,
        metrics=[roc_auc_score, f1_score, geometric_mean_score],
        n_splits=3, 
        experiment_repetitions=5, 
        random_state=None):
        self.oversampling_methods = oversampling_methods
        self.classifiers = classifiers
        self.metrics = metrics
        self.datasets = datasets
        self.n_splits = n_splits
        self.experiment_repetitions = experiment_repetitions
        self.random_state = random_state

    def _initialize_parameters(self):
        """Private method that initializes the experiment's parameters."""

        # Convert metrics to scorers
        self.scorers_ = [make_scorer(metric) for metric in self.metrics]

        # Read csv files and save them to a dictionary
        if isinstance(self.datasets, str):
            chdir(self.datasets)
            self.datasets = {}
            csv_files = [csv_file for csv_file in listdir() if match('^.+\.csv$', csv_file)]
            for csv_file in csv_files:
                dataset = pd.read_csv(csv_file)
                X, y = dataset.iloc[:, :-1], dataset.iloc[:, -1]
                dataset_name = sub(".csv", "", csv_file)
                self.datasets[dataset_name] = (X, y)
        
        # Create random states for experiments
        self.random_states_ = [self.random_state * index for index in range(self.experiment_repetitions)] if self.random_state is not None else [None] * self.experiment_repetitions
        
        # Extract names for experiments parameters
        self.classifiers_names_ = count_elements([classifier.__class__.__name__ for classifier in self.classifiers])
        self.oversampling_methods_names_ = count_elements([oversampling_method.__class__.__name__ if oversampling_method is not None else 'None' for oversampling_method in self.oversampling_methods])
        self.metrics_names_ = [sub('_', ' ', metric.__name__) for metric in self.metrics]
        self.datasets_names_ = self.datasets.keys()
        
    def run(self):
        """Runs the experimental procedure and calculates the cross validation 
        scores for each classifier, oversampling method, datasets and metric."""
        self._initialize_parameters()
        
        # Populate results dataframe
        results = pd.DataFrame(columns=['Dataset', 'Classifier', 'Oversampling method', 'Metric', 'CV score'])
        for experiment_ind, random_state in enumerate(self.random_states_):
            cv = StratifiedKFold(n_splits=self.n_splits, random_state=random_state, shuffle=True)
            for clf_ind, clf in enumerate(self.classifiers):
                clf.set_params(random_state=random_state)
                for oversampling_method_ind, oversampling_method in enumerate(self.oversampling_methods):
                    if oversampling_method is not None:
                        oversampling_method.set_params(random_state=random_state)
                    for scorer_ind, scorer in enumerate(self.scorers_):
                        for dataset_ind, (X, y) in enumerate(self.datasets.values()):
                            if oversampling_method is not None:
                                clf = make_pipeline(oversampling_method, clf)
                            clf_name = self.classifiers_names_[clf_ind]
                            om_name = self.oversampling_methods_names_[oversampling_method_ind]
                            metric_name = self.metrics_names_[scorer_ind]
                            dataset_name = list(self.datasets_names_)[dataset_ind]
                            cv_score = cross_val_score(clf, X, y, cv=cv, scoring=scorer).mean()
                            msg = 'Experiment: {}\nClassifier: {}\nOversampling method: {}\nMetric: {}\nDataset: {}\nCV score: {}\n\n'
                            print(msg.format(experiment_ind + 1, clf_name, om_name, metric_name, dataset_name, cv_score))
                            result = pd.DataFrame([[dataset_name, clf_name, om_name, metric_name, cv_score]], columns=results.columns)
                            results = results.append(result, ignore_index=True)
        
        # Group results dataframe by dataset, classifier and metric
        grouped_results = results.groupby(list(results.columns[:-1]))

        # Calculate mean and std results
        self.mean_results_ = grouped_results.mean().reset_index().rename(columns={'CV score': 'Mean CV score'})
        self.std_results_ = grouped_results.std().reset_index().rename(columns={'CV score': 'Std CV score'})
        
        # Transform mean results to wide format
        mean_results_wide = self.mean_results_.pivot_table(index=['Dataset', 'Classifier', 'Metric'], columns=['Oversampling method'], values='Mean CV score').reset_index()
        mean_results_wide.columns.rename(None, inplace=True)

        # Calculate mean ranking for each classifier/metric across datasets
        ranking_results = pd.concat([mean_results_wide[['Classifier', "Metric"]], mean_results_wide.apply(lambda row: len(row[3:]) - row[3:].argsort().argsort(), axis=1)], axis=1)    
        self.mean_ranking_results_ = round(ranking_results.groupby(['Classifier', 'Metric']).mean(), 2)

        # Calculate Friedman test p-values
        if len(self.oversampling_methods) > 2:
            self.friedman_test_results_ = ranking_results.groupby(['Classifier', 'Metric']).apply(extract_pvalue).reset_index().rename(columns={0: 'p-value'}).set_index(['Classifier', 'Metric'])
        else:
            self.friedman_test_results_ = 'Friedman test is not applied. More than two oversampling methods are needed.'