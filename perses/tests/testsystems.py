"""
Test systems for perses automated design.

Examples
--------

Alanine dipeptide in various environments (vacuum, implicit, explicit):

>>> from perses.tests.testsystems import AlaninDipeptideSAMS
>>> testsystem = AlanineDipeptideTestSystem()
>>> system_generator = testsystem.system_generator['explicit']
>>> sams_sampler = testsystem.sams_sampler['explicit']

TODO
----
* Have all PersesTestSystem subclasses automatically subjected to a battery of tests.
* Add short descriptions to each class through a class property.

"""

__author__ = 'John D. Chodera'

################################################################################
# IMPORTS
################################################################################

from simtk import openmm, unit
from simtk.openmm import app
import os, os.path
import sys, math
import numpy as np
from functools import partial
from pkg_resources import resource_filename
from openeye import oechem
from openmmtools import testsystems

################################################################################
# CONSTANTS
################################################################################

from perses.samplers.thermodynamics import kB

################################################################################
# TEST SYSTEMS
################################################################################

class PersesTestSystem(object):
    """
    Create a consistent set of samplers useful for testing.

    Properties
    ----------
    environments : list of str
        Available environments
    topologies : dict of simtk.openmm.app.Topology
        Initial system Topology objects; topologies[environment] is the topology for `environment`
    positions : dict of simtk.unit.Quantity of [nparticles,3] with units compatible with nanometers
        Initial positions corresponding to initial Topology objects
    system_generators : dict of SystemGenerator objects
        SystemGenerator objects for environments
    proposal_engines : dict of ProposalEngine
        Proposal engines
    themodynamic_states : dict of thermodynamic_states
        Themodynamic states for each environment
    mcmc_samplers : dict of MCMCSampler objects
        MCMCSampler objects for environments
    exen_samplers : dict of ExpandedEnsembleSampler objects
        ExpandedEnsembleSampler objects for environments
    sams_samplers : dict of SAMSSampler objects
        SAMSSampler objects for environments
    designer : MultiTargetDesign sampler
        Example MultiTargetDesign sampler

    """
    def __init__(self):
        self.environments = list()
        self.topologies = dict()
        self.positions = dict()
        self.system_generators = dict()
        self.proposal_engines = dict()
        self.thermodynamic_states = dict()
        self.mcmc_samplers = dict()
        self.exen_samplers = dict()
        self.sams_samplers = dict()
        self.designer = None

class AlanineDipeptideTestSystem(PersesTestSystem):
    """
    Create a consistent set of SAMS samplers useful for testing PointMutationEngine on alanine dipeptide in various solvents.
    This is useful for testing a variety of components.

    Properties
    ----------
    environments : list of str
        Available environments: ['vacuum', 'explicit', 'implicit']
    topologies : dict of simtk.openmm.app.Topology
        Initial system Topology objects; topologies[environment] is the topology for `environment`
    positions : dict of simtk.unit.Quantity of [nparticles,3] with units compatible with nanometers
        Initial positions corresponding to initial Topology objects
    system_generators : dict of SystemGenerator objects
        SystemGenerator objects for environments
    proposal_engines : dict of ProposalEngine
        Proposal engines
    themodynamic_states : dict of thermodynamic_states
        Themodynamic states for each environment
    mcmc_samplers : dict of MCMCSampler objects
        MCMCSampler objects for environments
    exen_samplers : dict of ExpandedEnsembleSampler objects
        ExpandedEnsembleSampler objects for environments
    sams_samplers : dict of SAMSSampler objects
        SAMSSampler objects for environments
    designer : MultiTargetDesign sampler
        Example MultiTargetDesign sampler for implicit solvent hydration free energies

    Examples
    --------

    >>> from perses.tests.testsystems import AlanineDipeptideTestSystem
    >>> testsystem = AlanineDipeptideTestSystem()
    # Build a system
    >>> system = testsystem.system_generators['vacuum'].build_system(testsystem.topologies['vacuum'])
    # Retrieve a SAMSSampler
    >>> sams_sampler = testsystem.sams_samplers['implicit']

    """
    def __init__(self):
        super(AlanineDipeptideTestSystem, self).__init__()
        environments = ['explicit', 'implicit', 'vacuum']

        # Create a system generator for our desired forcefields.
        from perses.rjmc.topology_proposal import SystemGenerator
        system_generators = dict()
        system_generators['explicit'] = SystemGenerator(['amber99sbildn.xml', 'tip3p.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.CutoffPeriodic, 'nonbondedCutoff' : 9.0 * unit.angstrom, 'implicitSolvent' : None, 'constraints' : None },
            use_antechamber=False)
        system_generators['implicit'] = SystemGenerator(['amber99sbildn.xml', 'amber99_obc.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.NoCutoff, 'implicitSolvent' : app.OBC2, 'constraints' : None },
            use_antechamber=False)
        system_generators['vacuum'] = SystemGenerator(['amber99sbildn.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.NoCutoff, 'implicitSolvent' : None, 'constraints' : None },
            use_antechamber=False)

        # Create peptide in solvent.
        from openmmtools.testsystems import AlanineDipeptideExplicit, AlanineDipeptideImplicit, AlanineDipeptideVacuum
        from pkg_resources import resource_filename
        pdb_filename = resource_filename('openmmtools', 'data/alanine-dipeptide-gbsa/alanine-dipeptide.pdb')
        from simtk.openmm.app import PDBFile
        topologies = dict()
        positions = dict()
        pdbfile = PDBFile(pdb_filename)
        topologies['vacuum'] = pdbfile.getTopology()
        positions['vacuum'] = pdbfile.getPositions(asNumpy=True)
        topologies['implicit'] = pdbfile.getTopology()
        positions['implicit'] = pdbfile.getPositions(asNumpy=True)

        # Create molecule in explicit solvent.
        modeller = app.Modeller(topologies['vacuum'], positions['vacuum'])
        modeller.addSolvent(system_generators['explicit'].getForceField(), model='tip3p', padding=9.0*unit.angstrom)
        topologies['explicit'] = modeller.getTopology()
        positions['explicit'] = modeller.getPositions()

        # Set up the proposal engines.
        from perses.rjmc.topology_proposal import PointMutationEngine
        proposal_metadata = { 'ffxmls' : ['amber99sbildn.xml'] }
        proposal_engines = dict()
        allowed_mutations = [[('2','ALA')],[('2','VAL'),('2','LEU')]]
        for environment in environments:
            proposal_engines[environment] = PointMutationEngine(system_generators[environment], max_point_mutants=1, chain_id='1', proposal_metadata=proposal_metadata, allowed_mutations=allowed_mutations)

        # Generate systems
        systems = dict()
        for environment in environments:
            systems[environment] = system_generators[environment].build_system(topologies[environment])

        # Define thermodynamic state of interest.
        from perses.samplers.thermodynamics import ThermodynamicState
        thermodynamic_states = dict()
        temperature = 300*unit.kelvin
        pressure = 1.0*unit.atmospheres
        thermodynamic_states['explicit'] = ThermodynamicState(system=systems['explicit'], temperature=temperature, pressure=pressure)
        thermodynamic_states['implicit'] = ThermodynamicState(system=systems['implicit'], temperature=temperature)
        thermodynamic_states['vacuum']   = ThermodynamicState(system=systems['vacuum'], temperature=temperature)

        # Create SAMS samplers
        chemical_state_key = 'ACE-ALA-NME' # TODO: Fix this to whatever they decide is the way to formulate PointMutationEngine chemical state keys
        from perses.samplers.samplers import SamplerState, MCMCSampler, ExpandedEnsembleSampler, SAMSSampler
        mcmc_samplers = dict()
        exen_samplers = dict()
        sams_samplers = dict()
        for environment in environments:
            if environment == 'explicit':
                sampler_state = SamplerState(system=systems[environment], positions=positions[environment], box_vectors=systems[environment].getDefaultPeriodicBoxVectors())
            else:
                sampler_state = SamplerState(system=systems[environment], positions=positions[environment])
            mcmc_samplers[environment] = MCMCSampler(thermodynamic_states[environment], sampler_state)
            exen_samplers[environment] = ExpandedEnsembleSampler(mcmc_samplers[environment], topologies[environment], chemical_state_key, proposal_engines[environment])
            sams_samplers[environment] = SAMSSampler(exen_samplers[environment])

        # Create test MultiTargetDesign sampler.
        from perses.samplers.samplers import MultiTargetDesign
        target_samplers = { sams_samplers['implicit'] : 1.0, sams_samplers['vacuum'] : -1.0 }
        designer = MultiTargetDesign(target_samplers)

        # Store things.
        self.environments = environments
        self.topologies = topologies
        self.positions = positions
        self.system_generators = system_generators
        self.proposal_engines = proposal_engines
        self.thermodynamic_states = thermodynamic_states
        self.mcmc_samplers = mcmc_samplers
        self.exen_samplers = exen_samplers
        self.sams_samplers = sams_samplers
        self.designer = designer

class AlkanesTestSystem(PersesTestSystem):
    """
    Create a consistent set of samplers useful for testing SmallMoleculeProposalEngine on alkanes in various solvents.
    This is useful for testing a variety of components.

    Properties
    ----------
    environments : list of str
        Available environments: ['vacuum', 'explicit']
    topologies : dict of simtk.openmm.app.Topology
        Initial system Topology objects; topologies[environment] is the topology for `environment`
    positions : dict of simtk.unit.Quantity of [nparticles,3] with units compatible with nanometers
        Initial positions corresponding to initial Topology objects
    system_generators : dict of SystemGenerator objects
        SystemGenerator objects for environments
    proposal_engines : dict of ProposalEngine
        Proposal engines
    themodynamic_states : dict of thermodynamic_states
        Themodynamic states for each environment
    mcmc_samplers : dict of MCMCSampler objects
        MCMCSampler objects for environments
    exen_samplers : dict of ExpandedEnsembleSampler objects
        ExpandedEnsembleSampler objects for environments
    sams_samplers : dict of SAMSSampler objects
        SAMSSampler objects for environments
    designer : MultiTargetDesign sampler
        Example MultiTargetDesign sampler for explicit solvent hydration free energies

    Examples
    --------

    >>> from perses.tests.testsystems import AlkanesTestSystem
    >>> testsystem = AlkanesTestSystem()
    # Build a system
    >>> system = testsystem.system_generators['vacuum'].build_system(testsystem.topologies['vacuum'])
    # Retrieve a SAMSSampler
    >>> sams_sampler = testsystem.sams_samplers['explicit']

    """
    def __init__(self):
        super(AlkanesTestSystem, self).__init__()
        environments = ['explicit', 'vacuum']

        # Create a system generator for our desired forcefields.
        from perses.rjmc.topology_proposal import SystemGenerator
        system_generators = dict()
        from pkg_resources import resource_filename
        gaff_xml_filename = resource_filename('perses', 'data/gaff.xml')
        system_generators['explicit'] = SystemGenerator([gaff_xml_filename, 'tip3p.xml'],
            forcefield_kwargs={ 'nonbondedMethod' : app.CutoffPeriodic, 'nonbondedCutoff' : 9.0 * unit.angstrom, 'implicitSolvent' : None, 'constraints' : None })
        system_generators['vacuum'] = SystemGenerator([gaff_xml_filename],
            forcefield_kwargs={ 'nonbondedMethod' : app.NoCutoff, 'implicitSolvent' : None, 'constraints' : None })

        #
        # Create topologies and positions
        #
        topologies = dict()
        positions = dict()

        from openmoltools import forcefield_generators
        forcefield = app.ForceField(gaff_xml_filename, 'tip3p.xml')
        forcefield.registerTemplateGenerator(forcefield_generators.gaffTemplateGenerator)

        # Create molecule in vacuum.
        from perses.tests.utils import createOEMolFromSMILES, extractPositionsFromOEMOL
        smiles = 'CC' # current sampler state
        molecule = createOEMolFromSMILES("CC")
        topologies['vacuum'] = forcefield_generators.generateTopologyFromOEMol(molecule)
        positions['vacuum'] = extractPositionsFromOEMOL(molecule)

        # Create molecule in solvent.
        modeller = app.Modeller(topologies['vacuum'], positions['vacuum'])
        modeller.addSolvent(forcefield, model='tip3p', padding=9.0*unit.angstrom)
        topologies['explicit'] = modeller.getTopology()
        positions['explicit'] = modeller.getPositions()

        # Set up the proposal engines.
        from perses.rjmc.topology_proposal import SmallMoleculeSetProposalEngine
        proposal_metadata = { }
        proposal_engines = dict()
        molecules = ['C', 'CC', 'CCC', 'CCCC', 'CCCCC', 'CCCCCC']
        for environment in environments:
            proposal_engines[environment] = SmallMoleculeSetProposalEngine(molecules, topologies[environment], system_generators[environment])

        # Generate systems
        systems = dict()
        for environment in environments:
            systems[environment] = system_generators[environment].build_system(topologies[environment])

        # Define thermodynamic state of interest.
        from perses.samplers.thermodynamics import ThermodynamicState
        thermodynamic_states = dict()
        temperature = 300*unit.kelvin
        pressure = 1.0*unit.atmospheres
        thermodynamic_states['explicit'] = ThermodynamicState(system=systems['explicit'], temperature=temperature, pressure=pressure)
        thermodynamic_states['vacuum']   = ThermodynamicState(system=systems['vacuum'], temperature=temperature)

        # Create SAMS samplers
        chemical_state_key = smiles
        from perses.samplers.samplers import SamplerState, MCMCSampler, ExpandedEnsembleSampler, SAMSSampler
        mcmc_samplers = dict()
        exen_samplers = dict()
        sams_samplers = dict()
        for environment in environments:
            if environment == 'explicit':
                sampler_state = SamplerState(system=systems[environment], positions=positions[environment], box_vectors=systems[environment].getDefaultPeriodicBoxVectors())
            else:
                sampler_state = SamplerState(system=systems[environment], positions=positions[environment])
            mcmc_samplers[environment] = MCMCSampler(thermodynamic_states[environment], sampler_state)
            exen_samplers[environment] = ExpandedEnsembleSampler(mcmc_samplers[environment], topologies[environment], chemical_state_key, proposal_engines[environment])
            sams_samplers[environment] = SAMSSampler(exen_samplers[environment])

        # Create test MultiTargetDesign sampler.
        from perses.samplers.samplers import MultiTargetDesign
        target_samplers = { sams_samplers['explicit'] : 1.0, sams_samplers['vacuum'] : -1.0 }
        designer = MultiTargetDesign(target_samplers)

        # Store things.
        self.environments = environments
        self.topologies = topologies
        self.positions = positions
        self.system_generators = system_generators
        self.proposal_engines = proposal_engines
        self.thermodynamic_states = thermodynamic_states
        self.mcmc_samplers = mcmc_samplers
        self.exen_samplers = exen_samplers
        self.sams_samplers = sams_samplers
        self.designer = designer

def check_topologies(testsystem):
    """
    Check that all SystemGenerators can build systems for their corresponding Topology objects.
    """
    for environment in testsystem.environments:
        topology = testsystem.topologies[environment]
        try:
            testsystem.system_generators[environment].build_system(topology)
        except Exception as e:
            msg = str(e)
            msg += '\n'
            msg += "topology for environment '%s' cannot be built into a system" % environment
            from perses.tests.utils import show_topology
            show_topology(topology)
            raise Exception(msg)

def test_AlanineDipeptideTestSystem():
    """
    Testing AlanineDipeptideTestSystem...
    """
    from perses.tests.testsystems import AlanineDipeptideTestSystem
    testsystem = AlanineDipeptideTestSystem()
    # Check topologies
    check_topologies(testsystem)
    # Build a system
    system = testsystem.system_generators['vacuum'].build_system(testsystem.topologies['vacuum'])
    # Retrieve a SAMSSampler
    sams_sampler = testsystem.sams_samplers['implicit']

def test_AlkanesTestSystem():
    """
    Testing AlkanesTestSystem...
    """
    from perses.tests.testsystems import AlkanesTestSystem
    testsystem = AlkanesTestSystem()

    # Test topologies.
    check_topologies(testsystem)

    # Build a system
    system = testsystem.system_generators['vacuum'].build_system(testsystem.topologies['vacuum'])
    # Retrieve a SAMSSampler
    sams_sampler = testsystem.sams_samplers['explicit']
