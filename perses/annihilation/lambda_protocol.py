from __future__ import print_function
import numpy as np
import logging
import copy
from openmmtools.alchemy import AlchemicalState

logging.basicConfig(level=logging.NOTSET)
_logger = logging.getLogger("lambda_protocol")
_logger.setLevel(logging.INFO)


class LambdaProtocol(object):
    """Protocols for perturbing each of the compent energy terms in alchemical
    free energy simulations.
    """

    default_functions = {'lambda_sterics_core':
                         lambda x: x,
                         'lambda_electrostatics_core':
                         lambda x: x,
                         'lambda_sterics_insert':
                         lambda x: 2.0 * x if x < 0.5 else 1.0,
                         'lambda_sterics_delete':
                         lambda x: 0.0 if x < 0.5 else 2.0 * (x - 0.5),
                         'lambda_electrostatics_insert':
                         lambda x: 0.0 if x < 0.5 else 2.0 * (x - 0.5),
                         'lambda_electrostatics_delete':
                         lambda x: 2.0 * x if x < 0.5 else 1.0,
                         'lambda_bonds':
                         lambda x: x,
                         'lambda_angles':
                         lambda x: x,
                         'lambda_torsions':
                         lambda x: x
                         }

    # lambda components for each component,
    # all run from 0 -> 1 following master lambda
    def __init__(self, functions='default'):
        """Instantiates lambda protocol to be used in a free energy calculation.
        Can either be user defined, by passing in a dict, or using one
        of the pregenerated sets by passing in a string 'default', 'namd' or 'quarters'

        All protocols must begin and end at 0 and 1 respectively. Any energy term not defined
        in `functions` dict will be set to the function in `default_functions`

        Pre-coded options:
        default : ele and LJ terms of the old system are turned off between 0.0 -> 0.5
        ele and LJ terms of the new system are turned on between 0.5 -> 1.0
        core terms treated linearly

        quarters : 0.25 of the protocol is used in turn to individually change the
        (a) off old ele, (b) off old sterics, (c) on new sterics (d) on new ele
        core terms treated linearly

        namd : follows the protocol outlined here: https://pubs.acs.org/doi/full/10.1021/acs.jcim.9b00362#
        Jiang, Wei, Christophe Chipot, and Benoît Roux. "Computing Relative Binding Affinity of Ligands
        to Receptor: An Effective Hybrid Single-Dual-Topology Free-Energy Perturbation Approach in NAMD."
        Journal of chemical information and modeling 59.9 (2019): 3794-3802.

        ele-scaled : all terms are treated as in default, except for the old and new ele
        these are scaled with lambda^0.5, so as to be linear in energy, rather than lambda

        Parameters
        ----------
        type : str or dict, default='default'
            one of the predefined lambda protocols ['default','namd','quarters']
            or a dictionary

        Returns
        -------
        """
        self.functions = copy.deepcopy(functions)
        if type(self.functions) == dict:
            self.type = 'user-defined'
        elif type(self.functions) == str:
            self.functions = None # will be set later
            self.type = functions

        if self.functions is None:
            if self.type == 'default':
                self.functions = copy.deepcopy(LambdaProtocol.default_functions)
            elif self.type == 'namd':
                self.functions = {'lambda_sterics_core':
                                  lambda x: x,
                                  'lambda_electrostatics_core':
                                  lambda x: x,
                                  'lambda_sterics_insert':
                                  lambda x: (3. / 2.) * x if x < (2. / 3.) else 1.0,
                                  'lambda_sterics_delete':
                                  lambda x: 0.0 if x < (1. / 3.) else (x - (1. / 3.)) * (3. / 2.),
                                  'lambda_electrostatics_insert':
                                  lambda x: 0.0 if x < 0.5 else 2.0 * (x - 0.5),
                                  'lambda_electrostatics_delete':
                                  lambda x: 2.0 * x if x < 0.5 else 1.0,
                                  'lambda_bonds':
                                  lambda x: x,
                                  'lambda_angles':
                                  lambda x: x,
                                  'lambda_torsions':
                                  lambda x: x}
            elif self.type == 'quarters':
                self.functions = {'lambda_sterics_core':
                                  lambda x: x,
                                  'lambda_electrostatics_core':
                                  lambda x: x,
                                  'lambda_sterics_insert':
                                  lambda x: 0. if x < 0.5 else 1 if x > 0.75 else 4 * (x - 0.5),
                                  'lambda_sterics_delete':
                                  lambda x: 0. if x < 0.25 else 1 if x > 0.5 else 4 * (x - 0.25),
                                  'lambda_electrostatics_insert':
                                  lambda x: 0. if x < 0.75 else 4 * (x - 0.75),
                                  'lambda_electrostatics_delete':
                                  lambda x: 4.0 * x if x < 0.25 else 1.0,
                                  'lambda_bonds':
                                  lambda x: x,
                                  'lambda_angles':
                                  lambda x: x,
                                  'lambda_torsions':
                                  lambda x: x}
            elif self.type == 'ele-scaled':
                self.functions = {'lambda_electrostatics_insert':
                                   lambda x: 0.0 if x < 0.5 else ((2*(x-0.5))**0.5),
                                  'lambda_electrostatics_delete':
                                   lambda x: (2*x)**2 if x < 0.5 else 1.0
                                 }
            elif self.type == 'user-defined':
                self.functions = functions
            else:
                _logger.warning(f"""LambdaProtocol type : {self.type} not
                                  recognised. Allowed values are 'default',
                                  'namd' and 'quarters' and 'user-defined'.
                                  Setting LambdaProtocol functions to default. """)
                self.functions = LambdaProtocol.default_functions

        self._validate_functions()
        self._check_for_naked_charges()

    def _validate_functions(self,n=10):
        """Ensures that all the lambda functions adhere to the rules:
            - must begin at 0.
            - must finish at 1.
            - must be monotonically increasing

        Parameters
        ----------
        n : int, default 10
            number of grid points used to check monotonicity

        Returns
        -------
        """
        # the individual lambda functions that must be defined for
        required_functions = list(LambdaProtocol.default_functions.keys())

        for function in required_functions:
            if function not in self.functions:
                _logger.warning(f'function {function} is missing from lambda_functions')
                _logger.warning(f'adding default {function} from LambdaProtocol.default_functions')
                self.functions[function] = LambdaProtocol.default_functions[function]
            # assert that the function starts and ends at 0 and 1 respectively
            assert (self.functions[function](0.) == 0.
                    ), 'lambda functions must start at 0'
            assert (self.functions[function](1.) == 1.
                    ), 'lambda functions must end at 1'

            # now validatate that it's monotonic
            global_lambda = np.linspace(0., 1., n)
            sub_lambda = [self.functions[function](l) for l in global_lambda]
            difference = np.diff(sub_lambda)
            if all(i >= 0. for i in difference) == False:
                _logger.warning(f'The function {function} is not monotonic as typically expected.')
                _logger.warning('Simulating with non-monotonic function anyway')
        return

    def _check_for_naked_charges(self,n=10):
        global_lambda = np.linspace(0., 1., n)

        # checking unique new terms first
        ele = 'lambda_electrostatics_insert'
        sterics = 'lambda_sterics_insert'
        for l in global_lambda:
            e_val = self.functions[ele](l)
            s_val = self.functions[sterics](l)
            if e_val != 0.:
                assert (s_val != 0.)

        # checking unique old terms now
        ele = 'lambda_electrostatics_delete'
        sterics = 'lambda_sterics_delete'
        for l in global_lambda:
            e_val = self.functions[ele](l)
            s_val = self.functions[sterics](l)
            if e_val != 1.:
                assert (s_val != 1.)

    def get_functions(self):
        return self.functions

    def plot_functions(self,n=50):
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(10,5))

        global_lambda = np.linspace(0.,1.,n)
        for f in self.functions:
            plt.plot(global_lambda, [self.functions[f](l) for l in global_lambda], alpha=0.5, label=f)

        plt.xlabel('global lambda')
        plt.ylabel('sub-lambda')
        plt.legend()
        plt.show()


class RelativeAlchemicalState(AlchemicalState):
    """
    Relative AlchemicalState to handle all lambda parameters required for relative perturbations
    lambda = 1 refers to ON, i.e. fully interacting while
    lambda = 0 refers to OFF, i.e. non-interacting with the system
    all lambda functions will follow from 0 -> 1 following the master lambda
    lambda*core parameters perturb linearly
    lambda_sterics_insert and lambda_electrostatics_delete perturb in the first half of the protocol 0 -> 0.5
    lambda_sterics_delete and lambda_electrostatics_insert perturb in the second half of the protocol 0.5 -> 1
    Attributes
    ----------
    lambda_sterics_core
    lambda_electrostatics_core
    lambda_sterics_insert
    lambda_sterics_delete
    lambda_electrostatics_insert
    lambda_electrostatics_delete
    """

    class _LambdaParameter(AlchemicalState._LambdaParameter):
        pass

    lambda_sterics_core = _LambdaParameter('lambda_sterics_core')
    lambda_electrostatics_core = _LambdaParameter('lambda_electrostatics_core')
    lambda_sterics_insert = _LambdaParameter('lambda_sterics_insert')
    lambda_sterics_delete = _LambdaParameter('lambda_sterics_delete')
    lambda_electrostatics_insert = _LambdaParameter('lambda_electrostatics_insert')
    lambda_electrostatics_delete = _LambdaParameter('lambda_electrostatics_delete')

    def set_alchemical_parameters(self, global_lambda,
                                  lambda_protocol=LambdaProtocol()):
       """Set each lambda value according to the lambda_functions protocol.
       The undefined parameters (i.e. those being set to None) remain
       undefined.
       Parameters
       ----------
       lambda_value : float
           The new value for all defined parameters.
       """
       self.global_lambda = global_lambda
       for parameter_name in lambda_protocol.functions:
           lambda_value = lambda_protocol.functions[parameter_name](global_lambda)
           setattr(self, parameter_name, lambda_value)


# REST Protocol!
class RESTProtocol(object):
    lambda_default_functions = {'lambda_sterics_core':
                             lambda x, beta0, beta: x,
                             'lambda_electrostatics_core':
                             lambda x, beta0, beta: x,
                             'lambda_sterics_insert':
                             lambda x, beta0, beta: 2.0 * x if x < 0.5 else 1.0,
                             'lambda_sterics_delete':
                             lambda x, beta0, beta: 0.0 if x < 0.5 else 2.0 * (x - 0.5),
                             'lambda_electrostatics_insert':
                             lambda x, beta0, beta: 0.0 if x < 0.5 else 2.0 * (x - 0.5),
                             'lambda_electrostatics_delete':
                             lambda x, beta0, beta: 2.0 * x if x < 0.5 else 1.0,
                             'lambda_bonds':
                             lambda x, beta0, beta: x,
                             'lambda_angles':
                             lambda x, beta0, beta: x,
                             'lambda_torsions':
                             lambda x, beta0, beta: x
                             }
    default_functions = {'solute_scale': lambda x, beta0, beta : beta / beta0,
                         'inter_scale' : lambda x, beta0, beta : np.sqrt(beta / beta0)
                         }
    def __init__(self):
        self.functions = RESTProtocol.default_functions

class RESTProtocolV2(object):
    mod_functions = {'solute_scale': lambda x, beta0, beta : beta / beta0,
                         'inter_scale' : lambda x, beta0, beta : np.sqrt(beta / beta0),
                         'steric_scale' : lambda x, beta0, beta : beta / beta0 - 1,
                         'electrostatic_scale' : lambda x, beta0, beta : np.sqrt(beta / beta0) - 1,
                         'electrostatic_insert_scale' : lambda x, beta, beta0 : RESTProtocol.lambda_default_functions['lambda_electrostatics_insert'](x, beta, beta0)*(np.sqrt(beta/beta0) - 1.),
                         'electrostatic_delete_scale' : lambda x, beta, beta0 : (1. - RESTProtocol.lambda_default_functions['lambda_electrostatics_delete'](x, beta, beta0))*(beta/beta0 - 1.),
                         'electrostatic_core_scale1' : lambda x, beta, beta0 : np.sqrt(beta/beta0) - 1,
                         'electrostatic_core_scale2' : lambda x, beta, beta0 : RESTProtocol.lambda_default_functions['lambda_electrostatics_core'](x, beta, beta0)*(np.sqrt(beta/beta0) - 1.),
                         'electrostatic_offset_core_scale1' : lambda x, beta, beta0 : np.sqrt(beta/beta0) - 1,
                         'electrostatic_offset_core_scale2' : lambda x, beta, beta0 : RESTProtocol.lambda_default_functions['lambda_electrostatics_core'](x, beta, beta0)*(np.sqrt(beta/beta0) - 1)
                         }
    
    default_functions = RESTProtocol.lambda_default_functions
    default_functions.update(mod_functions)
    def __init__(self):
        _logger.info(RESTProtocol.lambda_default_functions)
        _logger.info(RESTProtocolV2.mod_functions)
        _logger.info(RESTProtocol.lambda_default_functions.update(RESTProtocolV2.mod_functions))
        _logger.info(RESTProtocolV2.default_functions) 
        self.functions = RESTProtocolV2.default_functions


class RESTState(AlchemicalState):
    """
    REST State to handle all lambda parameters required for REST2 implementation.
    Attributes
    ----------
    solute_scale : solute scaling parameter
    inter_scale : inter-region scaling parameter
    """

    class _LambdaParameter(AlchemicalState._LambdaParameter):
        pass

    solute_scale = _LambdaParameter('solute_scale')
    inter_scale = _LambdaParameter('inter_scale')

    def set_alchemical_parameters(self,
                                  beta0,
                                  beta):
       """Set each lambda value according to the lambda_functions protocol.
       The undefined parameters (i.e. those being set to None) remain
       undefined.
       Parameters
       ----------
       lambda_value : float
           The new value for all defined parameters.
       """
       lambda_protocol = RESTProtocol()
       for parameter_name in lambda_protocol.functions:
           lambda_value = lambda_protocol.functions[parameter_name](beta0, beta)
           setattr(self, parameter_name, lambda_value)

class RESTStateV2(RESTState):
    """
    version 2 of RESTState
    """

    class _LambdaParameter(AlchemicalState._LambdaParameter):
        @staticmethod
        def lambda_validator(self, instance, parameter_value):
            if parameter_value is None:
                return parameter_value
            return float(parameter_value)

    solute_scale = _LambdaParameter('solute_scale')
    inter_scale = _LambdaParameter('inter_scale')
    electrostatic_scale = _LambdaParameter('electrostatic_scale')
    steric_scale = _LambdaParameter('steric_scale')

    def set_alchemical_parameters(self,
                                  beta0,
                                  beta):
       """Set each lambda value according to the lambda_functions protocol.
       The undefined parameters (i.e. those being set to None) remain
       undefined.
       Parameters
       ----------
       lambda_value : float
           The new value for all defined parameters.
       """
       lambda_protocol = RESTProtocolV2()
       for parameter_name in lambda_protocol.functions:
           lambda_value = lambda_protocol.functions[parameter_name](beta0, beta)
           setattr(self, parameter_name, lambda_value)
