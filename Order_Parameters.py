#!/usr/bin/env python

# Import prerequisite packages
# the missing packages can be installed using the command 
#pip install <package name>
#or
#pip3 install <package name>

import pandas as pd
import numpy as np
from pymatgen import Lattice, Structure, Molecule
from pymatgen.analysis import structure_analyzer, local_env
from pymatgen.analysis.chemenv.coordination_environments import voronoi
import sys
import pymatgen.io.ase
import math
import itertools
#import multiprocessing as mp
from operator import itemgetter
import re
import ase.io
from ase.atoms import Atoms
from ase.parallel import paropen
from ase.calculators.lammps import Prism, convert
import os
import random
from mpi4py import MPI

#-------------
# Communicator
#-------------
comm = MPI.COMM_WORLD


#Set the number of output decimals for the calculated features

n_decimals = 6

# Provide the lattice constants of bulk system for the reference to be used for the global features
# This are for the bulk Silicon:
# bulk_a=5.475
# bulk_b=5.475
# bulk_c=5.475

bulk_a=5.475
bulk_b=5.475
bulk_c=5.475










#\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
#LAMMPS functions

def read_lammps_data(fileobj, Z_of_type=None, style="full",
                     sort_by_id=False, units="metal"):
    """Method which reads a LAMMPS data file.

    sort_by_id: Order the particles according to their id. Might be faster to
    switch it off.
    Units are set by default to the style=metal setting in LAMMPS.
    """
    if isinstance(fileobj, str):
        fd = paropen(fileobj)
    else:
        fd = fileobj

    # load everything into memory
    lines = fd.readlines()

    # begin read_lammps_data
    comment = None
    N = None
    # N_types = None
    xlo = None
    xhi = None
    ylo = None
    yhi = None
    zlo = None
    zhi = None
    xy = None
    xz = None
    yz = None
    pos_in = {}
    travel_in = {}
    mol_id_in = {}
    charge_in = {}
    mass_in = {}
    vel_in = {}
    bonds_in = []
    angles_in = []
    dihedrals_in = []

    sections = [
        "Atoms",
        "Velocities",
        "Masses",
        "Charges",
        "Ellipsoids",
        "Lines",
        "Triangles",
        "Bodies",
        "Bonds",
        "Angles",
        "Dihedrals",
        "Impropers",
        "Impropers Pair Coeffs",
        "PairIJ Coeffs",
        "Pair Coeffs",
        "Bond Coeffs",
        "Angle Coeffs",
        "Dihedral Coeffs",
        "Improper Coeffs",
        "BondBond Coeffs",
        "BondAngle Coeffs",
        "MiddleBondTorsion Coeffs",
        "EndBondTorsion Coeffs",
        "AngleTorsion Coeffs",
        "AngleAngleTorsion Coeffs",
        "BondBond13 Coeffs",
        "AngleAngle Coeffs",
    ]
    header_fields = [
        "atoms",
        "bonds",
        "angles",
        "dihedrals",
        "impropers",
        "atom types",
        "bond types",
        "angle types",
        "dihedral types",
        "improper types",
        "extra bond per atom",
        "extra angle per atom",
        "extra dihedral per atom",
        "extra improper per atom",
        "extra special per atom",
        "ellipsoids",
        "lines",
        "triangles",
        "bodies",
        "xlo xhi",
        "ylo yhi",
        "zlo zhi",
        "xy xz yz",
    ]
    sections_re = "(" + "|".join(sections).replace(" ", "\\s+") + ")"
    header_fields_re = "(" + "|".join(header_fields).replace(" ", "\\s+") + ")"

    section = None
    header = True
    for line in lines:
        if comment is None:
            comment = line.rstrip()
        else:
            line = re.sub("#.*", "", line).rstrip().lstrip()
            if re.match("^\\s*$", line):  # skip blank lines
                continue

        # check for known section names
        m = re.match(sections_re, line)
        if m is not None:
            section = m.group(0).rstrip().lstrip()
            header = False
            continue

        if header:
            field = None
            val = None
            # m = re.match(header_fields_re+"\s+=\s*(.*)", line)
            # if m is not None: # got a header line
            #   field=m.group(1).lstrip().rstrip()
            #   val=m.group(2).lstrip().rstrip()
            # else: # try other format
            #   m = re.match("(.*)\s+"+header_fields_re, line)
            #   if m is not None:
            #       field = m.group(2).lstrip().rstrip()
            #       val = m.group(1).lstrip().rstrip()
            m = re.match("(.*)\\s+" + header_fields_re, line)
            if m is not None:
                field = m.group(2).lstrip().rstrip()
                val = m.group(1).lstrip().rstrip()
            if field is not None and val is not None:
                if field == "atoms":
                    N = int(val)
                # elif field == "atom types":
                #     N_types = int(val)
                elif field == "xlo xhi":
                    (xlo, xhi) = [float(x) for x in val.split()]
                elif field == "ylo yhi":
                    (ylo, yhi) = [float(x) for x in val.split()]
                elif field == "zlo zhi":
                    (zlo, zhi) = [float(x) for x in val.split()]
                elif field == "xy xz yz":
                    (xy, xz, yz) = [float(x) for x in val.split()]

        if section is not None:
            fields = line.split()
            if section == "Atoms":  # id *
                id = int(fields[0])
                if style == "full" and (len(fields) == 7 or len(fields) == 10):
                    # id mol-id type q x y z [tx ty tz]
                    pos_in[id] = (
                        int(fields[2]),
                        float(fields[4]),
                        float(fields[5]),
                        float(fields[6]),
                    )
                    mol_id_in[id] = int(fields[1])
                    charge_in[id] = float(fields[3])
                    if len(fields) == 10:
                        travel_in[id] = (
                            int(fields[7]),
                            int(fields[8]),
                            int(fields[9]),
                        )
                elif style == "atomic" and (
                        len(fields) == 5 or len(fields) == 8
                ):
                    # id type x y z [tx ty tz]
                    pos_in[id] = (
                        int(fields[1]),
                        float(fields[2]),
                        float(fields[3]),
                        float(fields[4]),
                    )
                    if len(fields) == 8:
                        travel_in[id] = (
                            int(fields[5]),
                            int(fields[6]),
                            int(fields[7]),
                        )
                elif (style in ("angle", "bond", "molecular")
                      ) and (len(fields) == 6 or len(fields) == 9):
                    # id mol-id type x y z [tx ty tz]
                    pos_in[id] = (
                        int(fields[2]),
                        float(fields[3]),
                        float(fields[4]),
                        float(fields[5]),
                    )
                    mol_id_in[id] = int(fields[1])
                    if len(fields) == 9:
                        travel_in[id] = (
                            int(fields[6]),
                            int(fields[7]),
                            int(fields[8]),
                        )
                elif (style == "charge"
                      and (len(fields) == 6 or len(fields) == 9)):
                    # id type q x y z [tx ty tz]
                    pos_in[id] = (
                        int(fields[1]),
                        float(fields[3]),
                        float(fields[4]),
                        float(fields[5]),
                    )
                    charge_in[id] = float(fields[2])
                    if len(fields) == 9:
                        travel_in[id] = (
                            int(fields[6]),
                            int(fields[7]),
                            int(fields[8]),
                        )
                else:
                    raise RuntimeError(
                        "Style '{}' not supported or invalid "
                        "number of fields {}"
                        "".format(style, len(fields))
                    )
            elif section == "Velocities":  # id vx vy vz
                vel_in[int(fields[0])] = (
                    float(fields[1]),
                    float(fields[2]),
                    float(fields[3]),
                )
            elif section == "Masses":
                mass_in[int(fields[0])] = float(fields[1])
            elif section == "Bonds":  # id type atom1 atom2
                bonds_in.append(
                    (int(fields[1]), int(fields[2]), int(fields[3]))
                )
            elif section == "Angles":  # id type atom1 atom2 atom3
                angles_in.append(
                    (
                        int(fields[1]),
                        int(fields[2]),
                        int(fields[3]),
                        int(fields[4]),
                    )
                )
            elif section == "Dihedrals":  # id type atom1 atom2 atom3 atom4
                dihedrals_in.append(
                    (
                        int(fields[1]),
                        int(fields[2]),
                        int(fields[3]),
                        int(fields[4]),
                        int(fields[5]),
                    )
                )

    # set cell
    cell = np.zeros((3, 3))
    cell[0, 0] = xhi - xlo
    cell[1, 1] = yhi - ylo
    cell[2, 2] = zhi - zlo
    if xy is not None:
        cell[1, 0] = xy
    if xz is not None:
        cell[2, 0] = xz
    if yz is not None:
        cell[2, 1] = yz

    # initialize arrays for per-atom quantities
    positions = np.zeros((N, 3))
    numbers = np.zeros((N), int)
    ids = np.zeros((N), int)
    types = np.zeros((N), int)
    if len(vel_in) > 0:
        velocities = np.zeros((N, 3))
    else:
        velocities = None
    if len(mass_in) > 0:
        masses = np.zeros((N))
    else:
        masses = None
    if len(mol_id_in) > 0:
        mol_id = np.zeros((N), int)
    else:
        mol_id = None
    if len(charge_in) > 0:
        charge = np.zeros((N), float)
    else:
        charge = None
    if len(travel_in) > 0:
        travel = np.zeros((N, 3), int)
    else:
        travel = None
    if len(bonds_in) > 0:
        bonds = [""] * N
    else:
        bonds = None
    if len(angles_in) > 0:
        angles = [""] * N
    else:
        angles = None
    if len(dihedrals_in) > 0:
        dihedrals = [""] * N
    else:
        dihedrals = None

    ind_of_id = {}
    # copy per-atom quantities from read-in values
    for (i, id) in enumerate(pos_in.keys()):
        # by id
        ind_of_id[id] = i
        if sort_by_id:
            ind = id - 1
        else:
            ind = i
        type = pos_in[id][0]
        positions[ind, :] = [pos_in[id][1], pos_in[id][2], pos_in[id][3]]
        if velocities is not None:
            velocities[ind, :] = [vel_in[id][0], vel_in[id][1], vel_in[id][2]]
        if travel is not None:
            travel[ind] = travel_in[id]
        if mol_id is not None:
            mol_id[ind] = mol_id_in[id]
        if charge is not None:
            charge[ind] = charge_in[id]
        ids[ind] = id
        # by type
        types[ind] = type
        if Z_of_type is None:
            numbers[ind] = type
        else:
            numbers[ind] = Z_of_type[type]
        if masses is not None:
            masses[ind] = mass_in[type]
    # convert units
    positions = convert(positions, "distance", units, "ASE")
    cell = convert(cell, "distance", units, "ASE")
    if masses is not None:
        masses = convert(masses, "mass", units, "ASE")
    if velocities is not None:
        velocities = convert(velocities, "velocity", units, "ASE")

    # create ase.Atoms
    at = Atoms(
        positions=positions,
        numbers=numbers,
        masses=masses,
        cell=cell,
        pbc=[True, True, True],
    )
    # set velocities (can't do it via constructor)
    if velocities is not None:
        at.set_velocities(velocities)
    at.arrays["id"] = ids
    at.arrays["type"] = types
    if travel is not None:
        at.arrays["travel"] = travel
    if mol_id is not None:
        at.arrays["mol-id"] = mol_id
    if charge is not None:
        at.arrays["initial_charges"] = charge
        at.arrays["mmcharges"] = charge.copy()

    if bonds is not None:
        for (type, a1, a2) in bonds_in:
            i_a1 = ind_of_id[a1]
            i_a2 = ind_of_id[a2]
            if len(bonds[i_a1]) > 0:
                bonds[i_a1] += ","
            bonds[i_a1] += "%d(%d)" % (i_a2, type)
        for i in range(len(bonds)):
            if len(bonds[i]) == 0:
                bonds[i] = "_"
        at.arrays["bonds"] = np.array(bonds)

    if angles is not None:
        for (type, a1, a2, a3) in angles_in:
            i_a1 = ind_of_id[a1]
            i_a2 = ind_of_id[a2]
            i_a3 = ind_of_id[a3]
            if len(angles[i_a2]) > 0:
                angles[i_a2] += ","
            angles[i_a2] += "%d-%d(%d)" % (i_a1, i_a3, type)
        for i in range(len(angles)):
            if len(angles[i]) == 0:
                angles[i] = "_"
        at.arrays["angles"] = np.array(angles)

    if dihedrals is not None:
        for (type, a1, a2, a3, a4) in dihedrals_in:
            i_a1 = ind_of_id[a1]
            i_a2 = ind_of_id[a2]
            i_a3 = ind_of_id[a3]
            i_a4 = ind_of_id[a4]
            if len(dihedrals[i_a1]) > 0:
                dihedrals[i_a1] += ","
            dihedrals[i_a1] += "%d-%d-%d(%d)" % (i_a2, i_a3, i_a4, type)
        for i in range(len(dihedrals)):
            if len(dihedrals[i]) == 0:
                dihedrals[i] = "_"
        at.arrays["dihedrals"] = np.array(dihedrals)

    at.info["comment"] = comment

    return at

###//////////////////////////////////









try:
        N_processors=int(sys.argv[1])
except:
        print('Enter the number of cores to use.')
        exit()

try:
        filepath=sys.argv[2]
except:
        print('Missing the path to configuration file.')
        exit()

try:
        outpath=sys.argv[3]
        featpath=outpath+'/features/'
        weigpath=outpath+'/weights/'
        mappath=outpath+'/map/'

        try:
            os.mkdir(featpath)
        except:
            pass
        try:
            os.mkdir(weigpath)
        except:
            pass
        try:
            os.mkdir(mappath)
        except:
            pass


except:
        print('Missing the output path.')
        exit()

try:
        ordering=sys.argv[4]
except:
        pass

try:
        sample=sys.argv[5]
except:
        sample=None
        pass

try:
        seed=sys.argv[6]
except:
        seed=None
        pass

#Get the order parameters





#Load the configuration

try:
        structure = read_lammps_data(filepath, style='atomic', sort_by_id=False, units='metal')
        structure = pymatgen.io.ase.AseAtomsAdaptor.get_structure(structure, cls=None)
except:
        try:
                structure = pymatgen.Structure.from_file(filepath)
        except:
                structure = ase.io.read(filepath)
                structure = pymatgen.io.ase.AseAtomsAdaptor.get_structure(structure, cls=None)


print(structure)

structure_save=structure.copy()

# Make a supercell to distinguish the atoms from its replicated counterparts (needed only for the small unit cells)

##\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\
# Check if a larger supercell is needed for the order parameters calculation

def checkIfDuplicates(listOfElems):
    ''' Check if given list contains any duplicates '''
    if len(listOfElems) == len(set(listOfElems)):
        return False
    else:
        return True
    
sizestructure=len(structure.atomic_numbers)

M=np.array([1,1,1])

if sizestructure<1000:
    result=True
    for w in range(sizestructure):
            while result:
                cell_dict=local_env.VoronoiNN(allow_pathological=True).get_nn_info(structure,w)
                neighbors=[cell_dict[v]['site_index'] for v in range(len(cell_dict))]
                result=checkIfDuplicates(neighbors)
                if result:
                        zer=[0,0,0]
                        zer[list(structure.lattice.abc).index(min(list(structure.lattice.abc)))]=1
                        M+=np.array(zer)
                        structure.make_supercell(M)
                        cell_dict=local_env.VoronoiNN(allow_pathological=True).get_nn_info(structure,w)
                        neighbors=[cell_dict[v]['site_index'] for v in range(len(cell_dict))]
                        result=checkIfDuplicates(neighbors)
    structure_save.make_supercell(M)
    structure = structure_save
##\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\                

#M=np.array([4,4,1])
#structure_save.make_supercell(M)
#structure = structure_save


scale=np.product(M)
sizestructure=len(structure.atomic_numbers)


print("The original unit cell has been increased by " + str(scale) +" times.")


lat_a=structure.lattice.a
lat_b=structure.lattice.b
lat_c=structure.lattice.c
lat_a=lat_a/np.round(lat_a/bulk_a,decimals=0)
lat_b=lat_b/np.round(lat_b/bulk_b,decimals=0)
lat_c=lat_c/np.round(lat_c/bulk_c,decimals=0)



face_areas_r=[]
neighbors=[]
element_nn_list=[]
face_area_dist=[]
neighbors_xyz=[]
volumes_r=[]


nn1_old=[]
nn2_old=[]
nn3_old=[]


def calculate_local_properties(dictionary, neighbors, core_atom, face_areas_r):
    dict_core=[dictionary[x] for x in [core_atom['symbol']]]
    dict_tot=[]
    
    
    for i in range(len(dict_core)):

        element_list_neigh=neighbors['element_nn_list'] 

        areas=face_areas_r 

    
        values_n=np.array([dictionary[x] for x in element_list_neigh])

        dict_tot.append(np.sum(areas*np.abs(values_n-dict_core[i]))/np.sum(areas))

    features=[np.max(dict_tot), np.min(dict_tot), np.mean(dict_tot), np.sum(np.abs(dict_tot-np.mean(dict_tot)))/len(dict_tot)]
    return features


def calculate_ionic_character(dictionary, neighbors, core_atom, face_areas_r):
    
    dict_core=[dictionary[x] for x in [core_atom['symbol']]]
    dict_tot=[]
    
    
    for i in range(len(dict_core)):

        element_list_neigh=neighbors['element_nn_list']
        areas=face_areas_r 

    
        values_n=np.array([dictionary[x] for x in element_list_neigh])

        dict_tot.append(np.sum(areas*np.abs(1-np.exp(-0.25*np.power((values_n-dict_core[i]), 2))))/np.sum(areas))

    features=[np.max(dict_tot), np.min(dict_tot), np.mean(dict_tot), np.sum(np.abs(dict_tot-np.mean(dict_tot)))/len(dict_tot)]
    return features
           

def get_neighbor_map(w):
            df=pd.DataFrame()
            cell_dict=local_env.VoronoiNN(allow_pathological=True).get_nn_info(structure,w)
            df['index']=[w]*len(cell_dict)
            df['symbol']=[str(structure._sites[w]).split()[-1]]*len(cell_dict)
            df['neighbors']=([cell_dict[v]['site_index'] for v in range(len(cell_dict))])
            df['element_nn_list']=([cell_dict[v]['site'].species_string for v in range(len(cell_dict))])
            df['volumes_r']=([cell_dict[v]['poly_info']['volume'] for v in range(len(cell_dict))])
            df['face_areas_r']=([cell_dict[v]['poly_info']['area'] for v in range(len(cell_dict))])   
            df['face_area_dist']=([cell_dict[v]['poly_info']['face_dist']*2 for v in range(len(cell_dict))])
            df['x']=[structure.cart_coords[w][0]]*len(cell_dict)
            df['y']=[structure.cart_coords[w][1]]*len(cell_dict)
            df['z']=[structure.cart_coords[w][2]]*len(cell_dict)
            df['neighbors_x']=([cell_dict[v]['site'].coords[0] for v in range(len(cell_dict))])
            df['neighbors_y']=([cell_dict[v]['site'].coords[1] for v in range(len(cell_dict))])
            df['neighbors_z']=([cell_dict[v]['site'].coords[2] for v in range(len(cell_dict))])
            df['dist_x']=abs(df['x']-df['neighbors_x'])
            df['dist_y']=abs(df['y']-df['neighbors_y'])
            df['dist_z']=abs(df['z']-df['neighbors_z'])
            df['sinphi2']=df['dist_y']**2/(df['dist_x']**2+df['dist_y']**2+1E-99)
            df['cosphi2']=df['dist_x']**2/(df['dist_x']**2+df['dist_y']**2+1E-99)
            df['sintheta2']=(df['dist_x']**2+df['dist_y']**2)/(df['dist_x']**2+df['dist_y']**2+df['dist_z']**2+1E-99)
            df['costheta2']=df['dist_z']**2/(df['dist_x']**2+df['dist_y']**2+df['dist_z']**2+1E-99)
            df['face_areas_r_a']=df['face_areas_r']*df['cosphi2']**0.5*df['sintheta2']**0.5
            df['face_areas_r_b']=df['face_areas_r']*df['sinphi2']**0.5*df['sintheta2']**0.5
            df['face_areas_r_c']=df['face_areas_r']*df['costheta2']**0.5
            return df



def get_atomic_env(w,df):
            df_atom=pd.DataFrame()
            df_atom['index']=[w]
            df_atom['symbol']=[str(structure._sites[w]).split()[-1]]
            df_atom['maximum_packing_efficiency']=[np.round((4/3*np.pi*(df['face_area_dist'].min()/2)**3)/(df['volumes_r'].sum()),decimals=n_decimals)]

            df_atom['bond_length']=[np.round(np.dot(df['face_area_dist'],np.transpose(df['face_areas_r']))/df['face_areas_r'].sum(),decimals=n_decimals)]
            df_atom['bond_length_a']=[np.round(np.dot(df['face_area_dist'],np.transpose(df['face_areas_r_a']))/df['face_areas_r_a'].sum(),decimals=n_decimals)]
            df_atom['bond_length_b']=[np.round(np.dot(df['face_area_dist'],np.transpose(df['face_areas_r_b']))/df['face_areas_r_b'].sum(),decimals=n_decimals)]
            df_atom['bond_length_c']=[np.round(np.dot(df['face_area_dist'],np.transpose(df['face_areas_r_c']))/df['face_areas_r_c'].sum(),decimals=n_decimals)]
            
            df_atom['var_bond_length']=[np.round(np.dot((df['face_area_dist']-df_atom['bond_length'].values)**2, np.transpose(df['face_areas_r']))/(df['face_areas_r'].sum()),decimals=n_decimals)]
            df_atom['var_bond_length_a']=[np.round(np.dot((df['face_area_dist']-df_atom['bond_length_a'].values)**2, np.transpose(df['face_areas_r_a']))/(df['face_areas_r_a'].sum()),decimals=n_decimals)]
            df_atom['var_bond_length_b']=[np.round(np.dot((df['face_area_dist']-df_atom['bond_length_b'].values)**2, np.transpose(df['face_areas_r_b']))/(df['face_areas_r_b'].sum()),decimals=n_decimals)]
            df_atom['var_bond_length_c']=[np.round(np.dot((df['face_area_dist']-df_atom['bond_length_c'].values)**2, np.transpose(df['face_areas_r_c']))/(df['face_areas_r_c'].sum()),decimals=n_decimals)]

            df_atom['min_cell_volume']=[np.round(df['volumes_r'].min(),decimals=n_decimals)]
            df_atom['max_cell_volume']=[np.round(df['volumes_r'].max(),decimals=n_decimals)]
            df_atom['mean_cell_volume']=[np.round(df['volumes_r'].mean(),decimals=n_decimals)]
            df_atom['mad_cell_volume']=[np.round(df['volumes_r'].mad(),decimals=n_decimals)]
            df_atom['tot_cell_volume']=[np.round(df['volumes_r'].sum(),decimals=n_decimals)]

            df_atom['mean_face_area']=[np.round(df['face_areas_r'].mean() ,decimals=n_decimals)]
            df_atom['max_face_area']=[np.round(df['face_areas_r'].max(),decimals=n_decimals)]
            df_atom['min_face_area']=[np.round(df['face_areas_r'].min(),decimals=n_decimals)]
            df_atom['mad_face_area']=[np.round(df['face_areas_r'].mad(),decimals=n_decimals)]
            df_atom['tot_face_area']=[np.round(df['face_areas_r'].sum(),decimals=n_decimals)]
            df_atom['mean_face_area_a']=[np.round(df['face_areas_r_a'].mean() ,decimals=n_decimals)]
            df_atom['max_face_area_a']=[np.round(df['face_areas_r_a'].max(),decimals=n_decimals)]
            df_atom['min_face_area_a']=[np.round(df['face_areas_r_a'].min(),decimals=n_decimals)]
            df_atom['mad_face_area_a']=[np.round(df['face_areas_r_a'].mad(),decimals=n_decimals)]
            df_atom['tot_face_area_a']=[np.round(df['face_areas_r_a'].sum(),decimals=n_decimals)]
            df_atom['mean_face_area_b']=[np.round(df['face_areas_r_b'].mean() ,decimals=n_decimals)]
            df_atom['max_face_area_b']=[np.round(df['face_areas_r_b'].max(),decimals=n_decimals)]
            df_atom['min_face_area_b']=[np.round(df['face_areas_r_b'].min(),decimals=n_decimals)]
            df_atom['mad_face_area_b']=[np.round(df['face_areas_r_b'].mad(),decimals=n_decimals)]
            df_atom['tot_face_area_b']=[np.round(df['face_areas_r_b'].sum(),decimals=n_decimals)]
            df_atom['mean_face_area_c']=[np.round(df['face_areas_r_c'].mean() ,decimals=n_decimals)]
            df_atom['max_face_area_c']=[np.round(df['face_areas_r_c'].max(),decimals=n_decimals)]
            df_atom['min_face_area_c']=[np.round(df['face_areas_r_c'].min(),decimals=n_decimals)]
            df_atom['mad_face_area_c']=[np.round(df['face_areas_r_c'].mad(),decimals=n_decimals)]
            df_atom['tot_face_area_c']=[np.round(df['face_areas_r_c'].sum(),decimals=n_decimals)]
            df_atom['coordination']=[np.round((df['face_areas_r'].sum())**2/((df['face_areas_r']**2).sum()),decimals=n_decimals)]
            df_atom['coordination_a']=[np.round((df['face_areas_r_a'].sum())**2/((df['face_areas_r_a']**2).sum()),decimals=n_decimals)]
            df_atom['coordination_b']=[np.round((df['face_areas_r_b'].sum())**2/((df['face_areas_r_b']**2).sum()),decimals=n_decimals)]
            df_atom['coordination_c']=[np.round((df['face_areas_r_c'].sum())**2/((df['face_areas_r_c']**2).sum()),decimals=n_decimals)]
            electronegativities={"name":'electronegativities',"H":1.90,"He":2.01,"Al":1.61, "In":1.78, "Ga": 1.81, "O":3.44, "Si" : 1.90, "Ge" : 2.01}
            local_properties=[electronegativities]
            for dictionary in local_properties:
                property_name='electronegativities' #[ k for k,v in locals().items() if v is dictionary][1]    
                features=calculate_local_properties(dictionary, df[['index','element_nn_list']], df[['index','symbol']].iloc[0], df['face_areas_r'])
                df_atom['max_'+property_name]=[np.round(features[0],decimals=n_decimals)]
                df_atom['min_'+property_name]=[np.round(features[1],decimals=n_decimals)]
                df_atom['mean_'+property_name]=[np.round(features[2],decimals=n_decimals)]
                df_atom['mad_'+property_name]=[np.round(features[3],decimals=n_decimals)]

            features=calculate_ionic_character(electronegativities, df[['index','element_nn_list']],  df[['index','symbol']].iloc[0], df['face_areas_r'])
            df_atom['max_ionic_character']=[np.round(features[0],decimals=n_decimals)]
            df_atom['min_ionic_character']=[np.round(features[1],decimals=n_decimals)]
            df_atom['mean_ionic_character']=[np.round(features[2],decimals=n_decimals)]
            df_atom['mad_ionic_character']=[np.round(features[3],decimals=n_decimals)]

            for dictionary in local_properties:
                property_name='electronegativities_a' #[ k for k,v in locals().items() if v is dictionary][1]    
                features=calculate_local_properties(dictionary, df[['index','element_nn_list']], df[['index','symbol']].iloc[0], df['face_areas_r_a'])
                df_atom['max_'+property_name]=[np.round(features[0],decimals=n_decimals)]
                df_atom['min_'+property_name]=[np.round(features[1],decimals=n_decimals)]
                df_atom['mean_'+property_name]=[np.round(features[2],decimals=n_decimals)]
                df_atom['mad_'+property_name]=[np.round(features[3],decimals=n_decimals)]

            features=calculate_ionic_character(electronegativities, df[['index','element_nn_list']],  df[['index','symbol']].iloc[0], df['face_areas_r_a'])

            df_atom['max_ionic_character_a']=[np.round(features[0],decimals=n_decimals)]
            df_atom['min_ionic_character_a']=[np.round(features[1],decimals=n_decimals)]
            df_atom['mean_ionic_character_a']=[np.round(features[2],decimals=n_decimals)]
            df_atom['mad_ionic_character_a']=[np.round(features[3],decimals=n_decimals)]

            for dictionary in local_properties:
                property_name='electronegativities_b' #[ k for k,v in locals().items() if v is dictionary][1]    
                features=calculate_local_properties(dictionary, df[['index','element_nn_list']], df[['index','symbol']].iloc[0], df['face_areas_r_b'])
                df_atom['max_'+property_name]=[np.round(features[0],decimals=n_decimals)]
                df_atom['min_'+property_name]=[np.round(features[1],decimals=n_decimals)]
                df_atom['mean_'+property_name]=[np.round(features[2],decimals=n_decimals)]
                df_atom['mad_'+property_name]=[np.round(features[3],decimals=n_decimals)]

            features=calculate_ionic_character(electronegativities, df[['index','element_nn_list']],  df[['index','symbol']].iloc[0], df['face_areas_r_b'])
            df_atom['max_ionic_character_b']=[np.round(features[0],decimals=n_decimals)]
            df_atom['min_ionic_character_b']=[np.round(features[1],decimals=n_decimals)]
            df_atom['mean_ionic_character_b']=[np.round(features[2],decimals=n_decimals)]
            df_atom['mad_ionic_character_b']=[np.round(features[3],decimals=n_decimals)]
            for dictionary in local_properties:
                property_name='electronegativities_c' #[ k for k,v in locals().items() if v is dictionary][1]    
                features=calculate_local_properties(dictionary, df[['index','element_nn_list']], df[['index','symbol']].iloc[0], df['face_areas_r_c'])
                df_atom['max_'+property_name]=[np.round(features[0],decimals=n_decimals)]
                df_atom['min_'+property_name]=[np.round(features[1],decimals=n_decimals)]
                df_atom['mean_'+property_name]=[np.round(features[2],decimals=n_decimals)]
                df_atom['mad_'+property_name]=[np.round(features[3],decimals=n_decimals)]

            features=calculate_ionic_character(electronegativities, df[['index','element_nn_list']],  df[['index','symbol']].iloc[0], df['face_areas_r_c'])
            df_atom['max_ionic_character_c']=[np.round(features[0],decimals=n_decimals)]
            df_atom['min_ionic_character_c']=[np.round(features[1],decimals=n_decimals)]
            df_atom['mean_ionic_character_c']=[np.round(features[2],decimals=n_decimals)]
            df_atom['mad_ionic_character_c']=[np.round(features[3],decimals=n_decimals)]
            df_atom['lat_a']=[np.round(lat_a,decimals=n_decimals)]
            df_atom['lat_b']=[np.round(lat_b,decimals=n_decimals)]
            df_atom['lat_c']=[np.round(lat_c,decimals=n_decimals)]
            df_atom['x']=[np.round(df['x'].mean(),decimals=n_decimals)]
            df_atom['y']=[np.round(df['y'].mean(),decimals=n_decimals)]
            df_atom['z']=[np.round(df['z'].mean(),decimals=n_decimals)]
            return df_atom



indices = np.arange(0,sizestructure,scale)

#print(indices)

if seed!=None:
    random.seed(int(seed))

if sample!=None:
    indices = random.sample(list(indices), int(len(indices)*float(sample)/100))

indices_needed=indices

#/////////////////////////////////////////////////////////////
# Try to RESTART 
#doneweights=os.listdir(weigpath)
#doneweights=[int(weight.split('.')[0]) for weight in doneweights]
#indices = np.setdiff1d(indices,doneweights)
#////////////////////////////////////////////////////////////


#/////////////////////////////////////////////////////////////
# Try to RESTART
if ordering=='False':
    donefeats=os.listdir(featpath)
    donefeats=[int(feat.split('.')[0]) for feat in donefeats]
    indices = np.setdiff1d(indices,donefeats)
else:
    donefeats=os.listdir(weigpath)
    donefeats=[int(feat.split('.')[0]) for feat in donefeats]
    indices = np.setdiff1d(indices,donefeats)
#////////////////////////////////////////////////////////////




def slice_iterable(iterable, chunk):
    """
    Slices an iterable into chunks of size n
    :param chunk: the number of items per slice
    :type chunk: int
    :type iterable: collections.Iterable
    :rtype: collections.Generator
    """
    _it = iter(iterable)
    return itertools.takewhile(
        bool, (tuple(itertools.islice(_it, chunk)) for _ in itertools.count(0))
    )


list_of_dict = [dict.fromkeys(indices) for _ in range(12)]




for dictionary in list_of_dict:
    for n in indices:
        dictionary[n]=[]
def worker(enumerated_comps):

    for ind, i in enumerated_comps:
         try:
                df_atom=pd.read_csv(featpath+str(i)+'.csv')
         except:
                df_all=get_neighbor_map(i)
                df_atom=get_atomic_env(i,df_all)
                df_atom.to_csv(featpath+str(i)+'.csv',index=False)
         if ordering!='False':
            try:
                df_all=pd.read_csv(mappath+str(i)+'.csv')
            except:
                df_all=get_neighbor_map(i)
                df_all.to_csv(mappath+str(i)+'.csv',index=False)

            element_0=df_all[(df_all['index']==i)]['symbol'].drop_duplicates().values
            
            w_tot_1=[]
            w_tot_2=[]
            w_tot_3=[]            
            w_tot_1_a=[]
            w_tot_2_a=[]
            w_tot_3_a=[]
            w_tot_1_b=[]
            w_tot_2_b=[]
            w_tot_3_b=[]
            w_tot_1_c=[]
            w_tot_2_c=[]
            w_tot_3_c=[]            
            for nn1 in df_all[(df_all['index']==i)]['neighbors']:
                if (i,nn1) not in nn1_old and nn1!=i:
                    nn1_old.append((i,nn1))
                    #nn1=(nn1-np.mod(nn1+scale,scale))
                    try:
                        df_all=pd.read_csv(mappath+str(nn1)+'.csv')
                    except:
                        df_all=get_neighbor_map(nn1)
                        df_all.to_csv(mappath+str(nn1)+'.csv',index=False)
                    area_tot_1=(df_all[df_all['index']==nn1]['face_areas_r']**1).sum()
                    area_tot_1_a=(df_all[df_all['index']==nn1]['face_areas_r_a']**1).sum()
                    area_tot_1_b=(df_all[df_all['index']==nn1]['face_areas_r_b']**1).sum()
                    area_tot_1_c=(df_all[df_all['index']==nn1]['face_areas_r_c']**1).sum()
                    for area_1, area_1_a, area_1_b, area_1_c, element_1, x, y, z in df_all[(df_all['index']==nn1)&(df_all['neighbors']==i)][['face_areas_r','face_areas_r_a','face_areas_r_b','face_areas_r_c','symbol','dist_x','dist_y','dist_z']].values:
                        if element_1!=element_0:
                            area_1=0
                            area_1_a=0
                            area_1_b=0
                            area_1_c=0                            
                        w_tot_1.append(area_1/area_tot_1)                            
                        w_tot_1_a.append(area_1_a/area_tot_1_a)
                        w_tot_1_b.append(area_1_b/area_tot_1_b)                        
                        w_tot_1_c.append(area_1_c/area_tot_1_c)

                        for nn2 in df_all[(df_all['index']==nn1)]['neighbors']: 
                            if (i,nn1,nn2) not in nn2_old and nn2!=i and nn2!=nn1 and nn1!=i:
                                nn2_old.append((i,nn1,nn2))
                                #nn2=(nn2-np.mod(nn2+scale,scale))
                                try:
                                    df_all=pd.read_csv(mappath+str(nn2)+'.csv')
                                except:
                                    df_all=get_neighbor_map(nn2)
                                    df_all.to_csv(mappath+str(nn2)+'.csv',index=False)

                                area_tot_2=(df_all[df_all['index']==nn2 ]['face_areas_r']**1).sum()
                                area_tot_2_a=(df_all[df_all['index']==nn2]['face_areas_r_a']**1).sum()
                                area_tot_2_b=(df_all[df_all['index']==nn2]['face_areas_r_b']**1).sum()
                                area_tot_2_c=(df_all[df_all['index']==nn2]['face_areas_r_c']**1).sum()                                
                                for area_2, area_2_a, area_2_b, area_2_c, element_2, x, y, z in df_all[(df_all['index']==nn2)&(df_all['neighbors']==nn1)][['face_areas_r','face_areas_r_a','face_areas_r_b','face_areas_r_c','symbol','dist_x','dist_y','dist_z']].values:
                                    if element_2!=element_1:
                                        area_2=0
                                        area_2_a=0
                                        area_2_b=0
                                        area_2_c=0                                        
                                    w_tot_2.append(area_2/area_tot_2*area_1/(area_tot_1-area_2))                                        
                                    w_tot_2_a.append(area_2_a/area_tot_2_a*area_1_a/(area_tot_1_a-area_2_a))
                                    w_tot_2_b.append(area_2_b/area_tot_2_b*area_1_b/(area_tot_1_b-area_2_b))
                                    w_tot_2_c.append(area_2_c/area_tot_2_c*area_1_c/(area_tot_1_c-area_2_c))
                                    
                                    for nn3 in df_all[(df_all['index']==nn2)]['neighbors']: 
                                        if (i,nn1,nn2,nn3) not in nn3_old and nn3!=i and nn3!=nn2 and nn3!=nn1 and nn1!=nn2 and nn2!=i and nn1!=i:
                                            nn3_old.append((i,nn1,nn2,nn3))
                                            #nn3=(nn3-np.mod(nn3+scale,scale))
                                            try:
                                                df_all=pd.read_csv(mappath+str(nn3)+'.csv')
                                            except:
                                                df_all=get_neighbor_map(nn3)
                                                df_all.to_csv(mappath+str(nn3)+'.csv',index=False)

                                            area_tot_3=(df_all[df_all['index']==nn3]['face_areas_r']**1).sum() 
                                            area_tot_3_a=(df_all[df_all['index']==nn3]['face_areas_r_a']**1).sum()
                                            area_tot_3_b=(df_all[df_all['index']==nn3]['face_areas_r_b']**1).sum()
                                            area_tot_3_c=(df_all[df_all['index']==nn3]['face_areas_r_c']**1).sum()                                                 
                                            for area_3, area_3_a, area_3_b, area_3_c, element_3, x, y, z in df_all[(df_all['index']==nn3)&(df_all['neighbors']==nn2)][['face_areas_r','face_areas_r_a','face_areas_r_b','face_areas_r_c','symbol','dist_x','dist_y','dist_z']].values:
                                                if element_3!=element_2:
                                                    area_3=0
                                                    area_3_a=0
                                                    area_3_b=0
                                                    area_3_c=0
                                                w_tot_3.append(area_3/area_tot_3*area_2/(area_tot_2-area_3)*area_1/(area_tot_1-area_2))                                                    
                                                w_tot_3_a.append(area_3_a/area_tot_3_a*area_2_a/(area_tot_2_a-area_3_a)*area_1_a/(area_tot_1_a-area_2_a))
                                                w_tot_3_b.append(area_3_b/area_tot_3_b*area_2_b/(area_tot_2_b-area_3_b)*area_1_b/(area_tot_1_b-area_2_b))
                                                w_tot_3_c.append(area_3_c/area_tot_3_c*area_2_c/(area_tot_2_c-area_3_c)*area_1_c/(area_tot_1_c-area_2_b))
            list_of_weights=[w_tot_1,w_tot_2,w_tot_3,w_tot_1_a,w_tot_2_a,w_tot_3_a,w_tot_1_b,w_tot_2_b,w_tot_3_b,w_tot_1_c,w_tot_2_c,w_tot_3_c]                                   
            df_w=pd.DataFrame(np.array([np.sum(list_of_weights[k]) for k in range(len(list_of_dict))]).reshape(-1, len(list_of_weights)),columns=['1_order','2_order','3_order','1_order_a','2_order_a','3_order_a','1_order_b','2_order_b','3_order_b','1_order_c','2_order_c','3_order_c']).round(n_decimals)
            df_w.to_csv(weigpath+str(i)+'.csv',index=False)
    return [(ind, 1) for ind, i in enumerated_comps]


all_tuples=indices

if len(indices)>0:
    N_processors = np.min([len(indices),N_processors])
else:
    N_processors = 1
comps = tuple(enumerate(all_tuples))

chunksize = int(math.ceil(len(comps)/N_processors))

jobs = tuple(slice_iterable(comps, chunksize))

#pool = mp.Pool(processes=N_processors)
#work_res = pool.map_async(worker, jobs)
#map(itemgetter(1), sorted(itertools.chain(*work_res.get())))
#pool.terminate()

##////////////////////////////
rank = comm.Get_rank()
size = comm.Get_size()


for i,task in enumerate(tuple(slice_iterable(comps,chunksize))):
  #This is how we split up the jobs.
  #The % sign is a modulus, and the "continue" means
  #"skip the rest of this bit and go to the next time
  #through the loop"
  # If we had e.g. 4 processors, this would mean
  # that proc zero did tasks 0, 4, 8, 12, 16, ...
  # and proc one did tasks 1, 5, 9, 13, 17, ...
  # and do on.
  if i%size!=rank: continue
  print(task)
  print("Task number %d  being done by processor %d of %d" % (i, rank, size))
  worker(task)

#my_N = 10
#N = my_N * comm.size

#if comm.rank == 0:
    #A = np.arange(len(indices), dtype=np.float64)
#    A = all_tuples
#    print('A',A)
#else:
    #Note that if I am not the root processor A is an empty array
#    A = np.empty(len(jobs), dtype=np.float64)

#my_A = np.empty(chunksize, dtype=np.float64)
#print('my_A',my_A)
#-------------------------
# Scatter data into my_A arrays
#-------------------------
#comm.Scatter( [A, MPI.DOUBLE], [my_A, MPI.DOUBLE] )

#if comm.rank == 0:
#   print("After Scatter:")
 
#for r in range(comm.size):
#    if comm.rank == r:
#        print("[%d] %s" % (comm.rank, my_A))
#    comm.Barrier()

#-------------------------
# Everybody is multiplying by 2
#-------------------------
#my_A **= 2
#comps = tuple(enumerate(my_A))
#print('my_A',my_A)

#if comm.rank==0:
#    for element in tuple(slice_iterable(comps,len(my_A))):
#        worker(element)

#-----------------------
# Allgather data into A again
#-----------------------
#comm.Allgather( [my_A, MPI.DOUBLE], [A, MPI.DOUBLE] )








##/////////////////////////////////
# Combine results
df_results=pd.DataFrame()
#for k in np.arange(0,sizestructure,scale):
#print(indices)
for k in indices_needed:
    #print(k)
    df_tmp1=pd.read_csv(featpath+str(k)+'.csv')
    #print(df_tmp1)
    if ordering=='True':
        df_tmp2=pd.read_csv(weigpath+str(k)+'.csv')
    else:
        df_tmp2=pd.DataFrame()
    df_tmp=pd.concat([df_tmp1,df_tmp2],axis=1,sort=False)
    df_results=pd.concat([df_results,df_tmp]).round(n_decimals)

#print(df_results)
#df_results['index']=(indices_needed-np.mod(indices_needed+scale,scale))
#print(indices_needed)
#print((indices_needed-np.mod(indices_needed+scale,scale)))

##CONCENTRATIONS

list_species=sorted(structure.species)

my_dict = {i:list_species.count(i) for i in list_species}


for i in range(len(list(my_dict.keys()))):
    df_results[str(list(my_dict.keys())[i])+"_conc"]=[(np.array(list(my_dict.values()))/sum(np.array(list(my_dict.values()))))[i]]*len(df_results)

#////////////////



#SAVE

df_results.to_csv(outpath+'/features.csv',index=False)



#///////////////////////////////////////
