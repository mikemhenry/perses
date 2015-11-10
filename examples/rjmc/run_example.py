#!/bin/env python

"""
Example illustrating use of expanded ensembles framework to perform a generic expanded ensembles simulation over chemical species.

This could represent sampling of small molecules, protein mutants, or both.

"""


import numpy as np
from simtk import unit, openmm
from simtk.openmm import app
import openeye.oechem as oechem
import openeye.oeomega as oeomega
import openmoltools
from perses.rjmc.topology_proposal import SingleSmallMolecule
from perses.bias.bias_engine import BiasEngine
from perses.annihilation.alchemical_engine import AlchemicalEliminationEngine
from perses.rjmc.geometry import GeometryEngine
from perses.annihilation.ncmc_switching import NCMCEngine
from perses.rjmc.system_engine import SystemGenerator

def generate_initial_molecule(mol_smiles):
    """
    Generate an oemol with a geometry
    """
    mol = oechem.OEMol()
    oechem.OESmilesToMol(mol, mol_smiles)
    oechem.OEAddExplicitHydrogens(mol)
    omega = oeomega.OEOmega()
    omega.SetMaxConfs(1)
    omega(mol)
    return mol

def oemol_to_openmm_system(oemol, molecule_name):
    """
    Create an openmm system out of an oemol

    Returns
    -------
    system : openmm.System object
        the system from the molecule
    positions : [n,3] np.array of floats
    """
    _ , tripos_mol2_filename = openmoltools.openeye.molecule_to_mol2(oemol, tripos_mol2_filename=molecule_name + '.tripos.mol2', conformer=0, residue_name='MOL')
    gaff_mol2, frcmod = openmoltools.openeye.run_antechamber(molecule_name, tripos_mol2_filename)
    prmtop_file, inpcrd_file = openmoltools.utils.run_tleap(molecule_name, gaff_mol2, frcmod)
    prmtop = app.AmberPrmtopFile(prmtop_file)
    system = prmtop.createSystem(implicitSolvent=app.OBC1)
    crd = app.AmberInpcrdFile(inpcrd_file)
    return system, crd.getPositions(asNumpy=True), prmtop.topology


def run():
    # Create initial model system, topology, and positions.
    smiles_list = ["CC", "CCC", "CCCC"]
    initial_molecule = generate_initial_molecule("CC")
    initial_sys, initial_pos, initial_top = oemol_to_openmm_system(initial_molecule, "ligand_old")
    smiles = 'CC'

    # Run parameters
    temperature = 300.0 * unit.kelvin # temperature
    pressure = 1.0 * unit.atmospheres # pressure
    collision_rate = 5.0 / unit.picoseconds # collision rate for Langevin dynamics


    #Create proposal metadata, such as the list of molecules to sample (SMILES here)
    proposal_metadata = {'smiles_list': smiles_list}
    transformation = SingleSmallMolecule(proposal_metadata)

    #initialize weight calculation engine, along with its metadata
    bias_calculator = BiasEngine(smiles_list)

    #Initialize AlchemicalEliminationEngine
    alchemical_metadata = {'data':0} #ignored
    alchemical_engine = AlchemicalEliminationEngine(alchemical_metadata)

    #Initialize NCMC engines.
    switching_timestep = 1.0 * unit.femtosecond # timestep for NCMC velocity Verlet integrations
    switching_nsteps = 10 # number of steps to use in NCMC integration
    switching_functions = { # functional schedules to use in terms of `lambda`, which is switched from 0->1 for creation and 1->0 for deletion
        'alchemical_sterics' : 'lambda',
        'alchemical_electrostatics' : 'lambda',
        'alchemical_bonds' : 'lambda',
        'alchemical_angles' : 'lambda',
        'alchemical_torsionss' : 'lambda'
        }
    ncmc_engine = NCMCEngine(temperature=temperature, timestep=switching_timestep, nsteps=switching_nsteps, functions=switching_functions)

    #initialize GeometryEngine
    geometry_metadata = {'data': 0} #currently ignored
    geometry_engine = GeometryEngine(geometry_metadata)

    # Run a anumber of iterations.
    niterations = 10
    for i in range(niterations):
        # Store old (system, topology, positions).

        # Propose a transformation from one chemical species to another.
        # QUESTION: This could depend on the geometry; could it not?
                               # The metadata might contain information about the topology, such as the SMILES string or amino acid sequence.
        # QUESTION: Could we instead initialize a transformation object once as
        # transformation = topology_proposal.Transformation(metametadata)
        # and then do
        # [new_topology, new_system, new_metadata] = transformation.propose(old_topology, old_system, old_metadata)?
        top_proposal = transformation.propose(system, topology, positions, state_metadata) # QUESTION: Is this a Topology object or some other container?

        # QUESTION: What about instead initializing StateWeight once, and then using
        # log_state_weight = state_weight.computeLogStateWeight(new_topology, new_system, new_metadata)?
        log_weight = bias_calculator.generate_bias(top_proposal)

        # Create a new System object from the proposed topology.
        # QUESTION: Do we want to isolate the system creation from the Transformation proposal? This does seem like something that *could* be pretty well isolated.
        # QUESTION: Should we at least create only one SystemGenerator, like
        # system_generator = SystemGenerator(forcefield, etc)
        # new_system = system_generator.createSystem(new_topology)
        new_system = system_generator.new_system(top_proposal)
        print(top_proposal)

        # Perform alchemical transformation.

        # Alchemically eliminate atoms being removed.
        # QUESTION: We need the alchemical transformation to eliminate the atoms being removed, right? So we need old topology/system and intermediate topology/system.
        # What if we had a method that took the old/new (topology, system, metadata) and generated some information about the transformation?
        # At minimum, we need to know what atoms are being eliminated/introduced.  We might also need to identify some System for the "intermediate" with scaffold atoms that are shared,
        # since charges and types may need to be modified?
        old_alchemical_system = alchemical_engine.make_alchemical_system(system, top_proposal, direction='delete')
        print(old_alchemical_system)
        [ncmc_old_positions, ncmc_elimination_logp] = ncmc_engine.integrate(old_alchemical_system, positions, direction='delete')
        print(ncmc_old_positions)
        print(ncmc_elimination_logp)

        # Generate coordinates for new atoms and compute probability ratio of old and new probabilities.
        # QUESTION: Again, maybe we want to have the geometry engine initialized once only?
        geometry_proposal = geometry_engine.propose(top_proposal, new_system, ncmc_old_positions)

        # Alchemically introduce new atoms.
        # QUESTION: Similarly, this needs to introduce new atoms.  We need to know both intermediate toplogy/system and new topology/system, right?
        new_alchemical_system = alchemical_engine.make_alchemical_system(new_system, top_proposal, direction='create')
        [ncmc_new_positions, ncmc_introduction_logp] = ncmc_engine.integrate(new_alchemical_system, geometry_proposal.new_positions, direction='insert')
        print(ncmc_new_positions)
        print(ncmc_introduction_logp)

        # Compute total log acceptance probability, including all components.
        logp_accept = top_proposal.logp + geometry_proposal.logp + ncmc_elimination_logp + ncmc_introduction_logp + log_weight - current_log_weight
        print(logp_accept)

        # Accept or reject.
        if (logp_accept>=0.0) or (np.random.uniform() < np.exp(logp_accept)):
            # Accept.
            (system, topology, positions, current_log_weight) = (new_system, top_proposal.new_topology, ncmc_new_positions, log_weight)
        else:
            # Reject.
            pass

#
# MAIN
#

if __name__=="__main__":
    run()
