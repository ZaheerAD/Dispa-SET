"""
This file gathers different functions used in the DispaSET pre-processing tools

@author: Sylvain Quoilin (sylvain.quoilin@ec.europa.eu)
"""

from __future__ import division

import logging
import sys

import numpy as np
import pandas as pd

from ..misc.str_handler import clean_strings, shrink_to_64


def incidence_matrix(sets, set_used, parameters, param_used):
    """ 
    This function generates the incidence matrix of the lines within the nodes
    A particular case is considered for the node "Rest Of the World", which is no explicitely defined in DispaSET
    """

    for i in range(len(sets[set_used])):
        if 'RoW' not in sets[set_used][i]:
            first_country = sets[set_used][i][0:2]
            second_country = sets[set_used][i][6:8]
        elif 'RoW' == sets[set_used][i][0:3]:
            first_country = sets[set_used][i][0:3]
            second_country = sets[set_used][i][7:9]
        elif 'RoW' == sets[set_used][i][6:9]:
            first_country = sets[set_used][i][0:2]
            second_country = sets[set_used][i][6:9]
        else:
            logging.error('The format of the interconnection is not valid.')
            sys.exit(1)

        for j in range(len(sets['n'])):
            if first_country == sets['n'][j]:
                parameters[param_used]['val'][i, j] = -1
            elif second_country == sets['n'][j]:
                parameters[param_used]['val'][i, j] = 1

    return parameters[param_used]


def interconnections(Simulation_list, NTC_inter, Historical_flows):
    """
    Function that checks for the possible interconnections of the countries included
    in the simulation. If the interconnections occurs between two of the countries
    defined by the user to perform the simulation with, it extracts the NTC between 
    those two countries. If the interconnection occurs between one of the countries
    selected by the user and one country outside the simulation, it extracts the 
    physical flows; it does so for each pair (country inside-country outside) and 
    sums them together creating the interconnection of this country with the RoW.

    :param Simulation_list:     List of simulated countries
    :param NTC:                 Day-ahead net transfer capacities (pd dataframe)
    :param Historical_flows:    Historical flows (pd dataframe)
    """
    
    index = NTC_inter.index.intersection(Historical_flows.index)
    if len(index)==0:
        logging.error('The two input dataframes (NTCs and Historical flows) must have the same index. No common values have been found')
        sys.exit(1)
    elif len(index) < len(NTC_inter) or len(index) < len(Historical_flows):
        diff = np.maximum(len(Historical_flows),len(NTC_inter)) - len(index)
        logging.warn('The two input dataframes (NTCs and Historical flows) do not share the same index, although some values are common. The intersection has been considered and ' + str(diff) + ' data points have been lost')
    # Checking that all values are positive:
    if (NTC_inter.values < 0).any():
        pos = np.where(NTC_inter.values < 0)
        logging.warn('WARNING: At least NTC value is negative, for example in line ' + str(NTC_inter.columns[pos[1][0]]) + ' and time step ' + str(NTC_inter.index[pos[0][0]]))
    if (Historical_flows.values < 0).any():
        pos = np.where(Historical_flows.values < 0)
        logging.warn('WARNING: At least one historical flow is negative, for example in line ' + str(Historical_flows.columns[pos[1][0]]) + ' and time step ' + str(Historical_flows.index[pos[0][0]]))
    all_connections = []
    simulation_connections = []
    # List all connections from the dataframe headers:
    ConList = Historical_flows.columns.tolist() + [x for x in NTC_inter.columns.tolist() if x not in Historical_flows.columns.tolist()]
    for connection in ConList:
        c = connection.split(' -> ')
        if len(c) != 2:
            logging.warn('WARNING: Connection "' + connection + '" in the interconnection tables is not properly named. It will be ignored')
        else:
            if c[0] in Simulation_list:
                all_connections.append(connection)
                if c[1] in Simulation_list:
                    simulation_connections.append(connection)
            elif c[1] in Simulation_list:
                all_connections.append(connection)

    df_countries_simulated = pd.DataFrame(index=index)
    for interconnection in simulation_connections:
        if interconnection in NTC_inter.columns:
            df_countries_simulated[interconnection] = NTC_inter[interconnection]
            logging.info('Detected interconnection ' + interconnection + '. The historical NTCs will be imposed as maximum flow value')
    interconnections1 = df_countries_simulated.columns

    # Display a warning if a country is isolated:
    for c in Simulation_list:
        if not any([c in conn for conn in interconnections1]) and len(Simulation_list)>1:
            logging.warn('Zone ' + c + ' does not appear to be connected to any other zone in the NTC table. It should be simulated in isolation')

    df_RoW_temp = pd.DataFrame(index=index)
    connNames = []
    for interconnection in all_connections:
        if interconnection in Historical_flows.columns and interconnection not in simulation_connections:
            df_RoW_temp[interconnection] = Historical_flows[interconnection]
            connNames.append(interconnection)

    compare_set = set()
    for k in connNames:
        if not k[0:2] in compare_set and k[0:2] in Simulation_list:
            compare_set.add(k[0:2])

    df_countries_RoW = pd.DataFrame(index=index)
    while compare_set:
        nameToCompare = compare_set.pop()
        exports = []
        imports = []
        for name in connNames:
            if nameToCompare[0:2] in name[0:2]:
                exports.append(connNames.index(name))
                logging.info('Detected interconnection ' + name + ', happening between a simulated zone and the rest of the world. The historical flows will be imposed to the model')
            elif nameToCompare[0:2] in name[6:8]:
                imports.append(connNames.index(name))
                logging.info('Detected interconnection ' + name + ', happening between the rest of the world and a simulated zone. The historical flows will be imposed to the model')

        flows_out = pd.concat(df_RoW_temp[connNames[exports[i]]] for i in range(len(exports)))
        flows_out = flows_out.groupby(flows_out.index).sum()
        flows_out.name = nameToCompare + ' -> RoW'
        df_countries_RoW[nameToCompare + ' -> RoW'] = flows_out
        flows_in = pd.concat(df_RoW_temp[connNames[imports[j]]] for j in range(len(imports)))
        flows_in = flows_in.groupby(flows_in.index).sum()
        flows_in.name = 'RoW -> ' + nameToCompare
        df_countries_RoW['RoW -> ' + nameToCompare] = flows_in
    interconnections2 = df_countries_RoW.columns
    inter = list(interconnections1) + list(interconnections2)
    return (df_countries_simulated, df_countries_RoW, inter)



def clustering(plants, method='Standard', Nslices=20, PartLoadMax=0.1, Pmax=30):
    """
    Merge excessively disaggregated power Units.

    :param plants:          Pandas dataframe with each power plant and their characteristics (following the DispaSET format)
    :param method:          Select clustering method ('Standard'/'LP'/None)
    :param Nslices:         Number of slices used to fingerprint each power plant characteristics. slices in the power plant data to categorize them  (fewer slices involves that the plants will be aggregated more easily)
    :param PartLoadMax:     Maximum part-load capability for the unit to be clustered
    :param Pmax:            Maximum power for the unit to be clustered
    :return:                A list with the merged plants and the mapping between the original and merged units
    """

    # Checking the the required columns are present in the input pandas dataframe:
    required_inputs = ['Unit', 'PowerCapacity', 'PartLoadMin', 'RampUpRate', 'RampDownRate', 'StartUpTime',
                       'MinUpTime', 'MinDownTime', 'NoLoadCost', 'StartUpCost', 'Efficiency']
    for input in required_inputs:
        if input not in plants.columns:
            logging.error("The plants dataframe requires a '" + input + "' column for clustering")
            sys.exit(1)
    if not "Nunits" in plants:
        plants['Nunits'] = 1

    # Checking the validity of the selected clustering method
    OnlyOnes = (plants['Nunits'] == 1).all()
    if method in ['Standard','MILP']:
        if not OnlyOnes:
            logging.warn("The standard (or MILP) clustering method is only applicable if all values of the Nunits column in the power plant data are set to one. At least one different value has been encountered. No clustering will be applied")
    elif method == 'LP clustered':
        if not OnlyOnes:
            logging.warn("The LP clustering method aggregates all the units of the same type. Individual units are not considered")
            # Modifying the table to remove multiple-units plants:
            for key in ['PowerCapacity', 'STOCapacity', 'STOMaxChargingPower','InitialPower']:
                if key in plants:
                    plants.loc[:,key] = plants.loc[:,'Nunits'] * plants.loc[:,key]
            plants['Nunits'] = 1
            OnlyOnes = True
    elif method == 'LP':
        pass
    elif method == 'Integer clustering':
        pass
    elif method == 'No clustering':
        pass
    else:
        logging.error('Method argument ("' + str(method) + '") not recognized in the clustering function')
        sys.exit(1)

    # Number of units:
    Nunits = len(plants)
    plants.index = range(Nunits)

    # Definition of the mapping variable, from the old power plant list the new (merged) one:
    map_old_new = np.zeros(Nunits)
    map_plant_orig = []

    # Slicing:
    bounds = {'PartLoadMin': np.linspace(0, 1, Nslices), 'RampUpRate': np.linspace(0, 1, Nslices),
              'RampDownRate': np.linspace(0, 1, Nslices), 'StartUpTime': _mylogspace(0, 36, Nslices),
              'MinUpTime': _mylogspace(0, 168, Nslices), 'MinDownTime': _mylogspace(0, 168, Nslices),
              'NoLoadCost': np.linspace(0, 50, Nslices), 'StartUpCost': np.linspace(0, 500, Nslices),
              'Efficiency': np.linspace(0, 1, Nslices)}

    # Definition of the fingerprint value of each power plant, i.e. the pattern of the slices number in which each of
    # its characteristics falls:
    fingerprints = []
    fingerprints_merged = []
    for i in plants.index:
        fingerprints.append([_find_nearest(bounds['PartLoadMin'], plants['PartLoadMin'][i]),
                             _find_nearest(bounds['RampUpRate'], plants['RampUpRate'][i]),
                             _find_nearest(bounds['RampDownRate'], plants['RampDownRate'][i]),
                             _find_nearest(bounds['StartUpTime'], plants['StartUpTime'][i]),
                             _find_nearest(bounds['MinUpTime'], plants['MinUpTime'][i]),
                             _find_nearest(bounds['MinDownTime'], plants['MinDownTime'][i]),
                             _find_nearest(bounds['NoLoadCost'], plants['NoLoadCost'][i]),
                             _find_nearest(bounds['StartUpCost'], plants['StartUpCost'][i]),
                             _find_nearest(bounds['Efficiency'], plants['Efficiency'][i])])

    # Definition of the merged power plants dataframe:
    plants_merged = pd.DataFrame(columns=plants.columns)

    # Find the columns containing string values (in addition to "Unit")
    #    string_keys = []
    #    for i in range(len(plants.columns)):
    #        if plants.columns[i] != 'Unit' and plants.dtypes[i] == np.dtype('O'):
    #            string_keys.append(plants.columns[i])
    string_keys = ['Zone', 'Technology', 'Fuel','CHPType']
    # First, fill nan values:
    for key in string_keys:
        plants[key].fillna('',inplace=True)

    for i in plants.index:  # i is the plant to be added to the new list
        merged = False
        for j in plants_merged.index:  # j corresponds to the clustered plants
            same_type = all([plants[key].fillna('')[i] == plants_merged[key].fillna('')[j] for key in
                             string_keys])
            same_fingerprint = (fingerprints[i] == fingerprints_merged[j])
            low_pmin = (plants['PartLoadMin'][i] <= PartLoadMax)
            low_pmax = (plants['PowerCapacity'][i] <= Pmax)
            highly_flexible = plants['RampUpRate'][i] > 1 / 60 and (plants['RampDownRate'][i] > 1 / 60) and (
            plants['StartUpTime'][i] < 1) and (plants['MinDownTime'][i] <= 1) and (plants['MinUpTime'][i] <= 1)
            cluster = OnlyOnes and same_type and ((same_fingerprint and low_pmin) or highly_flexible or low_pmax)
            if method in ('Standard','MILP') and cluster:  # merge the two plants in plants_merged:
                P_old = plants_merged['PowerCapacity'][j]  # Old power in plants_merged
                P_add = plants['PowerCapacity'][i]  # Additional power to be added
                for key in plants_merged:
                    if key in ['RampUpRate', 'RampDownRate', 'MinUpTime', 'MinDownTime', 'NoLoadCost', 'Efficiency',
                               'MinEfficiency', 'STOChargingEfficiency', 'CO2Intensity', 'STOSelfDischarge','CHPPowerToHeat','CHPPowerLossFactor']:
                        # Do a weighted average:
                        plants_merged.loc[j, key] = (plants_merged[key][j] * P_old + plants[key][i] * P_add) / (
                        P_add + P_old)
                    elif key in ['PowerCapacity', 'STOCapacity', 'STOMaxChargingPower','InitialPower']:
                        # Do a sum:
                        plants_merged.loc[j, key] = plants_merged[key][j] + plants[key][i]
                    elif key in ['PartLoadMin', 'StartUpTime']:
                        # Take the minimum
                        plants_merged.loc[j, key] = np.minimum(plants_merged[key][j] * P_old,
                                                               plants[key][i] * P_add) / (P_add + P_old)
                    elif key == 'RampingCost':
                        # The starting cost must be added to the ramping cost
                        Cost_to_fullload = P_add * (1 - plants['PartLoadMin'][i]) * plants['RampingCost'][i] + \
                                           plants['StartUpCost'][i]
                        plants_merged.loc[j, key] = (P_old * plants_merged[key][j] + Cost_to_fullload) / (P_old + P_add)
                    elif key == 'Nunits':
                        plants_merged.loc[j, key] = 1
                map_old_new[i] = j
                map_plant_orig[j].append(i)
                merged = True
                break
            elif method == 'LP clustered' and same_type and OnlyOnes:
                P_old = plants_merged['PowerCapacity'][j]  # Old power in plants_merged
                P_add = plants['PowerCapacity'][i]  # Additional power to be added
                for key in plants_merged:
                    if key in ['RampUpRate', 'RampDownRate', 'MinUpTime', 'MinDownTime', 'NoLoadCost', 'Efficiency',
                               'MinEfficiency', 'STOChargingEfficiency', 'CO2Intensity', 'STOSelfDischarge']:
                        # Do a weighted average:
                        plants_merged.loc[j, key] = (plants_merged[key][j] * P_old + plants[key][i] * P_add) / (
                        P_add + P_old)
                    elif key in ['PowerCapacity', 'STOCapacity', 'STOMaxChargingPower','InitialPower']:
                        # Do a sum:
                        plants_merged.loc[j, key] = plants_merged[key][j] + plants[key][i]
                    elif key in ['PartLoadMin', 'StartUpTime']:
                        # impose 0
                        plants_merged.loc[j, key] = 0
                    elif key == 'RampingCost':
                        # The starting cost must be added to the ramping cost
                        Cost_to_fullload = P_add * (1 - plants['PartLoadMin'][i]) * plants['RampingCost'][i] + \
                                           plants['StartUpCost'][i]
                        plants_merged.loc[j, key] = (P_old * plants_merged[key][j] + Cost_to_fullload) / (P_old + P_add)
                    elif key == 'Nunits':
                        plants_merged.loc[j, key] = 1
                map_old_new[i] = j
                map_plant_orig[j].append(i)
                merged = True
                break        
            elif method == 'Integer clustering' and same_type:
                for key in plants_merged:
                    if key in ['PowerCapacity','RampUpRate', 'RampDownRate', 'MinUpTime', 'MinDownTime', 'NoLoadCost', 'Efficiency',
                               'MinEfficiency', 'STOChargingEfficiency', 'CO2Intensity', 'STOSelfDischarge', 
                               'STOCapacity', 'STOMaxChargingPower','InitialPower','PartLoadMin', 'StartUpTime','RampingCost']:
                        # Do a weighted average:
                        plants_merged.loc[j, key] = (plants_merged.loc[j,key] * plants_merged.loc[j,'Nunits'] + plants.loc[i,key] * plants.loc[i,'Nunits']) / (plants_merged.loc[j,'Nunits'] + plants.loc[i,'Nunits'])
                plants_merged.loc[j, 'Nunits'] = plants_merged.loc[j,'Nunits'] + plants.loc[i,'Nunits']
                        
                map_old_new[i] = j
                map_plant_orig[j].append(i)
                merged = True
                break

        if not merged:  # Add a new plant in plants_merged:
            plants_merged = plants_merged.append(plants.loc[i], ignore_index=True)
            plants_merged = plants_merged.copy()
            map_plant_orig.append([i])
            map_old_new[i] = len(map_plant_orig) - 1
            fingerprints_merged.append(fingerprints[i])

    Nunits_merged = len(plants_merged)
    mapping = {'NewIndex': {}, 'FormerIndexes': {}}
    #    mapping['NewIdx'] = map_plant_orig
    #    mapping['OldIdx'] = map_old_new
    # Modify the Unit names with the original index number. In case of merged plants, indicate all indexes + the plant type and fuel
    for j in range(Nunits_merged):
        if len(map_plant_orig[j]) == 1:  # The plant has not been merged
            NewName = str(map_plant_orig[j]) + ' - ' + plants_merged['Unit'][j]
            NewName = shrink_to_64(clean_strings(NewName))
            NewName = NewName.rstrip()                          # remove space at the end because it is not considered by gams
            plants_merged.loc[j, 'Unit'] = NewName
            mapping['FormerIndexes'][NewName] = [map_plant_orig[j][0]]
            mapping['NewIndex'][map_plant_orig[j][0]] = NewName
        else:
            all_stringkeys = ''
            for key in string_keys:
                all_stringkeys = all_stringkeys + ' - ' + plants_merged[key][j]
            NewName = str(map_plant_orig[j]) + all_stringkeys
            NewName = shrink_to_64(clean_strings(NewName))
            NewName = NewName.rstrip()                          # remove space at the end because it is not considered by gams
            plants_merged.loc[j, 'Unit'] = NewName
            list_oldplants = [x for x in map_plant_orig[j]]
            mapping['FormerIndexes'][NewName] = list_oldplants
            for oldplant in list_oldplants:
                mapping['NewIndex'][oldplant] = NewName

    # Transforming the start-up cost into ramping for the plants that did not go through any clustering:
    if method == 'LP clustered':
        for i in range(Nunits_merged):
            if plants_merged['RampingCost'][i] == 0:
                Power = plants_merged['PowerCapacity'][i]
                Start_up = plants_merged['StartUpCost'][i]
                plants_merged.loc[i, 'RampingCost'] = Start_up / Power
                
    # Correcting the Nunits field of the clustered plants (must be integer):
    elif method == 'Integer clustering':
        for idx in plants_merged.index:
            N = np.round(plants_merged.loc[idx,'Nunits'])
        for key in ['PowerCapacity', 'STOCapacity', 'STOMaxChargingPower','InitialPower','NoLoadCost']:
            if key in plants_merged.columns:
                plants_merged.loc[idx,key] = plants_merged.loc[idx,key] * N / plants_merged.loc[idx,'Nunits']
        plants_merged.loc[idx,'Nunits'] = N
                
    # Updating the index of the merged plants dataframe with the new unit names, after some cleaning:
    plants_merged.index = plants_merged['Unit']

    if Nunits != len(plants_merged):
        logging.info('Clustered ' + str(Nunits) + ' original units into ' + str(len(plants_merged)) + ' new units')
    else:
        logging.warn('Did not cluster any unit')
    return plants_merged, mapping

## Helpers

def _mylogspace(low, high, N):
    """
    Self-defined logspace function in which low and high are the first and last values of the space
    """
    # shifting all values so that low = 1
    space = np.logspace(0, np.log10(high + low + 1), N) - (low + 1)
    return (space)


def _find_nearest(array, value):
    """
    Self-defined function to find the index of the nearest value in a vector
    """
    idx = (np.abs(array - value)).argmin()
    return idx
