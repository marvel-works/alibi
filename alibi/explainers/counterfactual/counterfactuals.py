from scipy.optimize import minimize
from time import time
from .base import BaseCounterFactual
#from scipy.spatial.distance import cityblock
import numpy as np
from statsmodels import robust
from functools import reduce


def _reshape_X(X: np.array) -> np.array:
    """reshape batch flattening features dimentions.

    Parameters
    ----------
    X: np.array

    Returns
    -------
    flatten_batch: np.array
    """
    if len(X.shape) > 1:
        nb_features = reduce((lambda x, y: x * y), X.shape[1:])
        return X.reshape(X.shape[0], nb_features)
    else:
        return X


def _calculate_franges(X_train: np.array) -> list:
    """Calculates features ranges from train data

    Parameters
    ----------
    X_train: np.array; training fuatures vectors

    Returns
    -------
    f_ranges: list; Min ad Max values in dataset for each feature
    """
    X_train=_reshape_X(X_train)
    f_ranges = []
    for i in range(X_train.shape[1]):
        mi, ma = X_train[:, i].min(), X_train[:, i].max()
        f_ranges.append((mi, ma))
    return f_ranges


def _calculate_radius(f_ranges: list, epsilon: float = 1) -> list:
    """Scales the feature range h-l by parameter epsilon

    Parameters
    ----------
    f_ranges: list; Min ad Max values in dataset for each feature
    epsilon: float; scaling factor, default=1

    Returns
    -------
    rs: list; scaled ranges for each feature
    """
    rs = []
    for l, h in f_ranges:
        r = epsilon * (h - l)
        rs.append(r)
    return rs


def _generate_rnd_samples(X: np.array, rs: list, nb_samples: int, all_positive: bool = True) -> np.array:
    """Samples points from a uniform distribution around instance X

    Parameters
    ----------
    X: np.array; Central instance
    rs: list; scaled ranges for each feature
    nb_samples: int; NUmber of points to sample
    all_positive: bool; if True, will only sample positive values, default=True

    Return
    ------
    samples_in: np.array; Sampled points
    """
    X_flatten = X.flatten()
    lower_bounds, upper_bounds = X_flatten - rs, X_flatten + rs
    if all_positive:
        lower_bounds[lower_bounds < 0]=0
    samples_in = np.asarray([np.random.uniform(low=lower_bounds[i], high=upper_bounds[i], size=nb_samples)
                             for i in range(len(X_flatten))]).T
    return samples_in


def _generate_poisson_samples(X: np.array, nb_samples: int, all_positive: bool = True) -> np.array:
    """Samples points from a Poisson distribution around instance X

    Parameters
    ----------
    X: np.array; Central instance
    nb_samples: int; NUmber of points to sample
    all_positive: bool; if True, will only sample positive values, default=True

    Return
    ------
    samples_in: np.array; Sampled points
    """
    X_flatten = X.flatten()
    samples_in = np.asarray([np.random.poisson(lam=X_flatten[i], size=nb_samples) for i in range(len(X_flatten))]).T

    return samples_in


def _generate_gaussian_samples(X: np.array, rs: list,  nb_samples: int, all_positive: bool = True) -> np.array:
    """Samples points from a Gaussian distribution around instance X

    Parameters
    ----------
    X
        Central instance
    rs
        scaled standard deviations for each feature
    nb_samples
        Number of points to sample
    all_positive
        if True, will only sample positive values, default=True

    Return
    ------
    samples_in
        np.array; Sampled points
    """

    X_flatten = X.flatten()
    samples_in = np.asarray([np.random.normal(loc=X_flatten[i], scale=rs[i], size=nb_samples)
                             for i in range(len(X_flatten))]).T
    if all_positive:
        samples_in[samples_in<0]=0

    return samples_in


def _calculate_confidence_treshold(X: np.array, model: object, y_train: np.array) -> float:
    """Unused
    """
    preds = model.predict(X)
    assert isinstance(preds, np.array), 'predictions not in a np.array format. ' \
                                        'Prediction format: {}'.format(type(preds))
    pred_class = np.argmax(preds)
    p_class = len(y_train[np.where(y_train == pred_class)]) / len(y_train)
    return 1 - p_class


def _has_predict_proba(model: object) -> bool:
    """Check if model has method 'predict_proba'

    Parameters
    ----------
    model
        model instace

    Returns
    -------
    has_predict_proba
        returns True if the model instance has a 'predict_proba' meethod, False otherwise
    """
    if hasattr(model, 'predict_proba'):
        return True
    else:
        return False


def _predict(model: object, X: np.array) -> np.array:
    """Model prediction function wrapper.

    Parameters
    ----------
    model
        model's instance

    Returns
    -------
    predictions
        Predictions array
    """
    if _has_predict_proba(model):
        return model.predict_proba(X)
    else :
        return model.predict(X)


class CounterFactualRandomSearch(BaseCounterFactual):
    """
    """

    def __init__(self, model, sampling_method='poisson', epsilon=0.1, epsilon_step=0.1, max_epsilon=5,
                 nb_samples=100, metric='l1_distance', aggregate_by='closest'):
        """

        Parameters
        ----------
        model
            model instance
        sampling_method
            probability distribution for sampling; Poisson, Uniform or Gaussian.
        epsilon
            scale parameter to calculate sampling region. Determines the size of the neighbourhood around the
            instance to explain in which the sampling is performed.
        epsilon_step
            incremental step for epsilon in the expanding spheres approach.
        max_epsilon
            maximum value of epsilon at which the search is stopped
        nb_samples
            Number os points to sample at every iteration
        metric
            distance metric between features vectors. Can be 'l1_distance', 'mad_distance' or a callable function
            taking 2 vectors as input and returning a float
        aggregate_by
            method to choose the countefactual instance; 'closest' or 'mean'
        """
        super().__init__(model=model, sampling_method=sampling_method, epsilon=epsilon, epsilon_step=epsilon_step,
                         max_epsilon=max_epsilon, nb_samples=nb_samples, metric=metric, flip_treshold=None,
                         aggregate_by=aggregate_by, method=None, tollerance=None, maxiter=None,
                         initial_lam=None, lam_step=None, max_lam=None)

    def fit(self, X_train, y_train=None):
        """

        Parameters
        ----------
        X_train
            features vectors
        y_train
            targets

        Returns
        -------
        None
        """
        self.f_ranges = _calculate_franges(X_train)

    def explain(self, X: np.array) -> np.array:
        """Generate a counterfactual instance respect to the input instance X with the expanding neighbourhoods method.

        Parameters
        ----------
        X
            reference instance for counterfactuals

        Returns
        -------
        explaining_instance
            np.array of same shape as X; counterfactual instance

        """
        probas_x = _predict(self.model, X)
        pred_class = np.argmax(probas_x, axis=1)[0]
        max_proba_x = probas_x[:, pred_class]
        cond = False

        # find counterfactual instance with random sampling method
        while not cond:
            rs = _calculate_radius(f_ranges=self.f_ranges , epsilon=self.epsilon)

            if self.sampling_method=='uniform':
                samples_in = _reshape_X(_generate_rnd_samples(X, rs, self.nb_samples))
            elif self.sampling_method=='poisson':
                samples_in = _reshape_X(_generate_poisson_samples(X, self.nb_samples))
            elif self.sampling_method=='gaussian':
                samples_in = _reshape_X(_generate_gaussian_samples(X, rs, self.nb_samples))
            else:
                raise NameError('method {} not implemented'.format(self.sampling_method))

            probas_si = _predict(self.model, samples_in.reshape((samples_in.shape[0],) + X.shape[1:]))
            pred_classes = np.argmax(probas_si, axis=1)
            unique, counts = np.unique(pred_classes, return_counts=True)
            majority_class = unique[np.argmax(counts)]
            print('Original predicted class: {}; Majority class in sampled data: {}'.format(pred_class, majority_class))

            if self.aggregate_by == 'closest':
                cond = (pred_classes != pred_class).any()
            elif self.aggregate_by == 'mean':
                cond = (majority_class != pred_class)
            if cond:
                samples_flip = samples_in[np.where(pred_classes != pred_class)]
                distances = [self._metric_distance(samples_flip[i], X.flatten()) for i in range(len(samples_flip))]

                if self.aggregate_by == 'closest':
                    cf_instance=samples_flip[np.argmin(distances)].reshape(X.shape)
                elif self.aggregate_by == 'mean':
                    cf_instance = samples_flip.mean(axis=0).reshape(X.shape)
                else:
                    cf_instance = None
                    raise NameError('Supported values for arg  "aggragate_by": {}, {}'.format('closest', 'mean'))

                print('Epsilon', self.epsilon)
                print('==========================')
                print('Number of samples:', len(samples_in))
                print('Original predicted class {} with probability {}: '.format(pred_class, max_proba_x))
                print('Majority class in sampled data points ', majority_class)
                print('Closest flipped class: ',
                      pred_classes[np.where(pred_classes != pred_class)][np.argmin(distances)])
                print('Original instance shape:', X.shape)
                print('Counfact instance shape:', cf_instance.shape)
                print('L1 distance from X ', self._metric_distance(cf_instance.flatten(), X.flatten()))

                self.explaning_instance = cf_instance
                self.samples_flip = samples_flip
                self.features_values_diff = cf_instance.flatten() - X.flatten()
                self.l1_distance = self._metric_distance(cf_instance.flatten(), X.flatten())

            self.epsilon += self.epsilon_step
            if self.epsilon >= self.max_epsilon:
                break

        if self.explaning_instance is None:
            raise NameError('Instance not found')

        return self.explaning_instance


class CounterFactualAdversarialSearch(BaseCounterFactual):
    """
    """
    def __init__(self, model, method='OuterBoundary', tollerance=0, maxiter=300,
                 initial_lam=1, lam_step=0.5, max_lam=10, metric='mad_distance', flip_treshold=0.5):
        """

        Parameters
        ----------
        model
            model instance
        method
            algorithm used to find a counterfactual instance; 'OuterBoundary', 'Wachter' or 'InnerBoundary'
        tollerance
            minimum difference between predicted and predefined probabilities for the counterfactual instance
        maxiter
            maximum number of iterations of the optimizer
        initial_lam
            initial value of lambda parameter. Higher value of lambda will give more weight to prediction accuracy
            respect to proximity of the counterfactual instance with the original instance
        lam_step
            incremental step for lambda
        max_lam
            maximum value for lambda at which the search is stopped
        metric
            distance metric between features vectors. Can be 'l1_distance', 'mad_distance' or a callable function
            taking 2 vectors as input and returning a float
        flip_treshold
            probability at which the predicted class is considered flipped (e.g. 0.5 for binary classification)
        """
        super().__init__(model=model, sampling_method=None, epsilon=None, epsilon_step=None,
                         max_epsilon=None, nb_samples=None, metric=metric, aggregate_by=None,
                         method=method, tollerance=tollerance, flip_treshold=flip_treshold,
                         initial_lam=initial_lam, lam_step=lam_step, max_lam=max_lam, maxiter=maxiter)

    def fit(self, X_train, y_train=None):
        """

        Parameters
        ----------
        X_train
            features vectors
        y_train
            targets

        Returns
        -------
        None
        """
        self.f_ranges = _calculate_franges(X_train)
        self.mads = robust.mad(X_train, axis=0)+10e-10
        #self._norm = 1/np.abs(X_train - np.roll(X_train, 1, axis=0)).sum(axis=1).max()
        _samples=np.random.permutation(X_train)[:2000]
        _distances = []
        for i in range(_samples.shape[0]):
            _distances.append(self._metric_distance(_samples[i], np.roll(_samples, 1, axis=0)[i]))
        self._norm = 1.0/max(_distances)

    def explain(self, X):
        """

        Parameters
        ----------
        X
            instance to explain

        Returns
        -------
        explaning_instance
            counterfactual instance serving as an explanation

        """
        probas_x = _predict(self.model, X)
        pred_class = np.argmax(probas_x, axis=1)[0]
        max_proba_x = probas_x[:, pred_class]
        cond = False

        if self.method == 'Wachter' or self.method == 'OuterBoundary':
            classes_tmp = [i for i in range(probas_x.shape[1]) if i != pred_class]
            rs = _calculate_radius(f_ranges=self.f_ranges, epsilon=1)
            initial_instance = _generate_rnd_samples(X, rs, 1)
            initial_instance = _reshape_X(initial_instance)[0]

            def _countefactual_loss(x, classes=classes_tmp, XX=X.flatten(), lam=self.lam, yy=self.flip_treshold):
                pred_tmp = _predict(self.model, x.reshape(X.shape))[:, classes].max()
                loss_0 = lam*(pred_tmp - yy)**2
                loss_1 = self._norm*self._metric_distance(x, XX)
                print(loss_0, loss_1)
                return loss_0+loss_1

            def _contrains_diff(x, classes=classes_tmp, yy=self.flip_treshold, tollerance=self.tollerance):
                pred_tmp = _predict(self.model, x.reshape(X.shape))[:, classes].max()
                return -((pred_tmp - yy)**2) + tollerance

            def _contrains_pos(x, classes=classes_tmp, yy=self.flip_treshold):
                pred_tmp = _predict(self.model, x.reshape(X.shape))[:, classes].max()
                return pred_tmp - yy

            t_0 = time()

            while not cond :
                print('Starting minimization with Lambda = {}'.format(self.lam))
                cons = ({'type': 'ineq', 'fun': _contrains_diff},
                        {'type': 'ineq', 'fun': _contrains_pos})
                res = minimize(_countefactual_loss, initial_instance, constraints=cons,
                               method='COBYLA', options={'maxiter': self._maxiter})

                probas_exp = _predict(self.model, res.x.reshape(X.shape))
                pred_class_exp = np.argmax(probas_exp, axis=1)[0]
                max_proba_exp = probas_exp[:, pred_class_exp]
                cond = _contrains_diff(res.x)
                initial_instance = res.x

                self.lam += self.lam_step
                if self.lam >= self.max_lam:
                    break

            print('Minimization time: ', time() - t_0)
            self.explaning_instance = res.x.reshape(X.shape)

            #probas_exp = _predict(self.model, np.asarray(self.explaning_instance).reshape(X.shape))

            #pred_class_exp = np.argmax(probas_exp, axis=1)[0]
            #max_proba_exp = probas_exp[:, pred_class_exp]

            print('Original instance predicted class: {} with probability {}:'.format(pred_class, max_proba_x))
            print('Countfact instance predicted class: {} with probability {}:'.format(pred_class_exp, max_proba_exp))
            print('Original instance shape', X.shape)
            print('Countfact instance shape', self.explaning_instance.shape)
            print('L1 distance from X', self._metric_distance(self.explaning_instance.flatten(), X.flatten()))

        elif self.method == 'InnerBoundary':
            # find counterfactual instance with loss minimization method
            rs = _calculate_radius(f_ranges=self.f_ranges, epsilon=1)
            initial_instance = _generate_rnd_samples(X, rs, 1)
            initial_instance = _reshape_X(initial_instance)[0]

            def _countefactual_loss(x, XX=X.flatten(), lam=self.lam, yy=max_proba_x):
                preds_tmp = _predict(self.model , x.reshape(X.shape))[:, pred_class]
                return lam*(preds_tmp - yy)**2 + self._metric_distance(x, XX)

            def _contrains_diff(x, yy=max_proba_x, tollerance=self.tollerance):
                return (_predict(self.model, x.reshape(X.shape))[:, pred_class] - yy) ** 2 <= tollerance

            t_0 = time()

            while not cond :
                print('Starting minimization with Lambda = {}'.format(self.lam))
                cons = ({'type': 'ineq', 'fun': _contrains_diff})
                res = minimize(_countefactual_loss, initial_instance, method='COBYLA', constraints=cons)

                probas_exp = _predict(self.model, res.x.reshape(X.shape))
                pred_class_exp = np.argmax(probas_exp, axis=1)[0]
                max_proba_exp = probas_exp[:, pred_class_exp]
                cond = _contrains_diff(res.x)
                initial_instance = res.x

                self.lam += self.lam_step
                if self.lam >= self.max_lam:
                    break

            print('Minimization time: ', time() - t_0)
            self.explaning_instance = res.x.reshape(X.shape)

            #probas_exp = _predict(self.model, np.asarray(self.explaning_instance).reshape(X.shape))

            #pred_class_exp = np.argmax(probas_exp, axis=1)[0]
            #max_proba_exp = probas_exp[:, pred_class_exp]

            print('Original instance predicted class: {} with probability {}:'.format(pred_class, max_proba_x))
            print('Countfact instance predicted class: {} with probability {}:'.format(pred_class_exp, max_proba_exp))
            print('Original instance shape', X.shape)
            print('Countfact instance shape', self.explaning_instance.shape)
            print('L1 distance from X', self._metric_distance(self.explaning_instance.flatten(), X.flatten()))

        return self.explaning_instance