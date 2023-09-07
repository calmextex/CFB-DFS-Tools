import csv
import json
import math
import os
import random
import time
import numpy as np
import pulp as plp
import multiprocessing as mp
import pandas as pd
import statistics
# import fuzzywuzzy
import itertools
import collections
import re
from scipy.stats import norm, kendalltau, multivariate_normal, gamma
#import matplotlib.pyplot as plt
#import seaborn as sns


class CFB_GPP_Simulator:
    config = None
    player_dict = {}
    field_lineups = {}
    stacks_dict = {}
    gen_lineup_list = []
    roster_construction = []
    id_name_dict = {}
    salary = None
    optimal_score = None
    field_size = None
    team_list = []
    num_iterations = None
    site = None
    payout_structure = {}
    use_contest_data = False
    entry_fee = None
    use_lineup_input = None
    matchups = set()
    projection_minimum = 15
    randomness_amount = 100
    min_lineup_salary = 48000
    max_pct_off_optimal = 0.4
    teams_dict = collections.defaultdict(list)  # Initialize teams_dict
    correlation_rules = {}

    def __init__(
            self,
            site,
            field_size,
            num_iterations,
            use_contest_data,
            use_lineup_input,
    ):
        self.site = site
        self.use_lineup_input = use_lineup_input
        self.load_config()
        self.load_rules()

        projection_path = os.path.join(
            os.path.dirname(__file__),
            "../{}_data/{}".format(site, self.config["projection_path"]),
        )
        self.load_projections(projection_path)

        player_path = os.path.join(
            os.path.dirname(__file__),
            "../{}_data/{}".format(site, self.config["player_path"]),
        )
        self.load_player_ids(player_path)
        self.load_team_stacks()

        # ownership_path = os.path.join(
        #    os.path.dirname(__file__),
        #    "../{}_data/{}".format(site, self.config["ownership_path"]),
        # )
        # self.load_ownership(ownership_path)

        # boom_bust_path = os.path.join(
        #    os.path.dirname(__file__),
        #    "../{}_data/{}".format(site, self.config["boom_bust_path"]),
        # )
        # self.load_boom_bust(boom_bust_path)

        #       batting_order_path = os.path.join(
        #           os.path.dirname(__file__),
        #            "../{}_data/{}".format(site, self.config["batting_order_path"]),
        #        )
        #        self.load_batting_order(batting_order_path)

        if site == "dk":
            self.roster_construction = ['QB', 'RB', 'RB', 'WR', 'WR', 'WR', 'FLEX', 'S-FLEX']
            self.salary = 50000

        elif site == "fd":
            self.roster_construction = ['QB', 'RB', 'RB', 'WR', 'WR', 'WR', 'FLEX', 'S-FLEX']
            self.salary = 60000

        self.use_contest_data = use_contest_data
        if use_contest_data:
            contest_path = os.path.join(
                os.path.dirname(__file__),
                "../{}_data/{}".format(site, self.config["contest_structure_path"]),
            )
            self.load_contest_data(contest_path)
            print("Contest payout structure loaded.")
        else:
            self.field_size = int(field_size)
            self.payout_structure = {0: 0.0}
            self.entry_fee = 0

        # self.adjust_default_stdev()
        self.num_iterations = int(num_iterations)
        self.get_optimal()
        if self.use_lineup_input:
            self.load_lineups_from_file()
        # if self.match_lineup_input_to_field_size or len(self.field_lineups) == 0:
        # self.generate_field_lineups()
        self.load_correlation_rules()

    # make column lookups on datafiles case insensitive
    def lower_first(self, iterator):
        return itertools.chain([next(iterator).lower()], iterator)

    def load_rules(self):
        self.projection_minimum = int(self.config["projection_minimum"])
        self.randomness_amount = float(self.config["randomness"])
        self.min_lineup_salary = int(self.config["min_lineup_salary"])
        self.max_pct_off_optimal = float(self.config["max_pct_off_optimal"])
        self.pct_field_using_stacks = float(self.config['pct_field_using_stacks'])
        self.default_qb_var = float(self.config['default_qb_var'])
        self.default_skillpos_var = float(self.config['default_skillpos_var'])
        #self.default_def_var = float(self.config['default_def_var'])
        self.overlap_limit = float(self.config['num_players_vs_def'])
        self.pct_field_double_stacks = float(self.config['pct_field_double_stacks'])
        self.correlation_rules = self.config["custom_correlations"]

    # In order to make reasonable tournament lineups, we want to be close enough to the optimal that
    # a person could realistically land on this lineup. Skeleton here is taken from base `mlb_optimizer.py`
    def get_optimal(self):

        # print(s['Name'],s['ID'])
        print(self.player_dict)
        problem = plp.LpProblem('CFB', plp.LpMaximize)
        lp_variables = {self.player_dict[(player, pos_str, team)]['ID']: plp.LpVariable(
            str(self.player_dict[(player, pos_str, team)]['ID']), cat='Binary') for (player, pos_str, team) in
            self.player_dict}

        # set the objective - maximize fpts
        problem += plp.lpSum(self.player_dict[(player, pos_str, team)]['Fpts'] * lp_variables[
            self.player_dict[(player, pos_str, team)]['ID']]
                             for (player, pos_str, team) in self.player_dict), 'Objective'

        # Set the salary constraints
        problem += plp.lpSum(self.player_dict[(player, pos_str, team)]['Salary'] * lp_variables[
            self.player_dict[(player, pos_str, team)]['ID']]
                             for (player, pos_str, team) in self.player_dict) <= self.salary

        if self.site == 'dk':
            # Need 1 quarterback but can have 2 with S-Flex slot
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'QB' in self.player_dict[(player, pos_str, team)]['Position']) >= 1
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                    for (player, pos_str, team) in self.player_dict if
                                    'QB' in self.player_dict[(player, pos_str, team)]['Position']) <= 2
            # Need at least 2 RBs can have up to 4 with FLEX and S-Flex slots
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'RB' in self.player_dict[(player, pos_str, team)]['Position']) >= 2
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'RB' in self.player_dict[(player, pos_str, team)]['Position']) <= 4
            # Need at least 3 WRs can have up to 5 with FLEX slot and S-Flex slot
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'WR' in self.player_dict[(player, pos_str, team)]['Position']) >= 3
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'WR' in self.player_dict[(player, pos_str, team)]['Position']) <= 5
            # Can only roster 8 total players
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict) == 8
            # Max 6 per team in case of weird issues with stacking on short slates
            for team in self.team_list:
                problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                     for (player, pos_str, team) in self.player_dict if
                                     self.player_dict[(player, pos_str, team)]['Team'] == team) <= 6

        elif self.site == 'fd':
            # Need at least 1 QB can have 2 with SuperFlex slot
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'QB' in self.player_dict[(player, pos_str, team)]['Position']) >= 1
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'QB' in self.player_dict[(player, pos_str, team)]['Position']) <= 2
            # Need at least 2 RBs can have up to 4 with FLEX slot and SuperFlex slot
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'RB' in self.player_dict[(player, pos_str, team)]['Position']) >= 2
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'RB' in self.player_dict[(player, pos_str, team)]['Position']) <= 4
            # Need at least 3 WRs can have up to 5 with FLEX slot and SuperFlex slot
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'WR' in self.player_dict[(player, pos_str, team)]['Position']) >= 3
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict if
                                 'WR' in self.player_dict[(player, pos_str, team)]['Position']) <= 5
            # Can only roster 8 total players
            problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                 for (player, pos_str, team) in self.player_dict) == 8
            # Max 4 per team
            for team in self.team_list:
                problem += plp.lpSum(lp_variables[self.player_dict[(player, pos_str, team)]["ID"]]
                                     for (player, pos_str, team) in self.player_dict if
                                     self.player_dict[(player, pos_str, team)]['Team'] == team) <= 4

        # print(f"Problem Name: {problem.name}")
        # print(f"Sense: {problem.sense}")

        # # Print the objective
        # print("\nObjective:")
        # try:
        #     for v, coef in problem.objective.items():
        #         print(f"{coef}*{v.name}", end=' + ')
        # except Exception as e:
        #     print(f"Error while printing objective: {e}")

        # # Print the constraints
        # print("\nConstraints:")
        # for constraint in problem.constraints.values():
        #     try:
        #         # Extract the left-hand side, right-hand side, and the operator
        #         lhs = "".join(f"{coef}*{var.name}" for var, coef in constraint.items())
        #         rhs = constraint.constant
        #         if constraint.sense == 1:
        #             op = ">="
        #         elif constraint.sense == -1:
        #             op = "<="
        #         else:
        #             op = "="
        #         print(f"{lhs} {op} {rhs}")
        #     except Exception as e:
        #         print(f"Error while printing constraint: {e}")

        # # Print the variables
        # print("\nVariables:")
        # try:
        #     for v in problem.variables():
        #         print(f"{v.name}: LowBound={v.lowBound}, UpBound={v.upBound}, Cat={v.cat}")
        # except Exception as e:
        #     print(f"Error while printing variable: {e}")
        # Crunch!
        try:
            problem.solve(plp.PULP_CBC_CMD(msg=0))
        except plp.PulpSolverError:
            print('Infeasibility reached - only generated {} lineups out of {}. Continuing with export.'.format(
                len(self.num_lineups), self.num_lineups))
        except TypeError:
            for p, s in self.player_dict.items():
                if s["ID"] == 0:
                    print(s["Name"] + ' name mismatch between projections and player ids')
                if s['ID'] == '':
                    print(s['Name'] + ' name mismatch between projections and player ids')
                if s['ID'] is None:
                    print(s['Name'])

        score = str(problem.objective)
        for v in problem.variables():
            score = score.replace(v.name, str(v.varValue))

        self.optimal_score = eval(score)

    # Load player IDs for exporting
    def load_player_ids(self, path):
        with open(path, encoding="utf-8-sig") as file:
            reader = csv.DictReader(self.lower_first(file))
            for row in reader:
                name_key = "name" if self.site == "dk" else "nickname"
                player_name = row[name_key].replace("-", "#").lower().strip()
                # all players have FLEX and S-FLEX positions. QBs have S-FLEX
                position = [pos for pos in row['position'].split('/')]
                position.sort()
                # if qb not in position add flex and superflex
                if 'QB' not in position:
                    position.append('FLEX')
                    position.append('S-FLEX')
                # if QB is in position add S-FLEX
                else:
                    position.append('S-FLEX')

                team_key = "teamabbrev" if self.site == "dk" else "team"
                team = row[team_key]
                game_info = "game info" if self.site == "dk" else "game"
                match = re.search(pattern='(\w{2,5}@\w{2,5})', string=row[game_info])
                if match:
                    opp = match.groups()[0].split('@')
                    #print(opp[0], opp[1])
                    self.matchups.add((opp[0], opp[1]))
                    for m in opp:
                        #print(opp)
                        if m != team:
                            team_opp = m
                    opp = tuple(opp)

                pos_str = str(position)

                # add id, team, opp, matchup to player dict
                if (player_name, pos_str, team) in self.player_dict:
                    self.player_dict[(player_name, pos_str, team)]["ID"] = row["id"]
                    self.player_dict[(player_name, pos_str, team)]["Team"] = row[team_key]
                    self.player_dict[(player_name, pos_str, team)]["Opp"] = team_opp
                    self.player_dict[(player_name, pos_str, team)]["Matchup"] = opp
                self.id_name_dict[str(row["id"])] = row[name_key]



    def load_contest_data(self, path):
        with open(path, encoding="utf-8-sig") as file:
            reader = csv.DictReader(self.lower_first(file))
            for row in reader:
                if self.field_size is None:
                    self.field_size = int(row["field size"])
                if self.entry_fee is None:
                    self.entry_fee = float(row["entry fee"])
                # multi-position payouts
                if "-" in row["place"]:
                    indices = row["place"].split("-")
                    # print(indices)
                    # have to add 1 to range to get it to generate value for everything
                    for i in range(int(indices[0]), int(indices[1]) + 1):
                        # print(i)
                        # Where I'm from, we 0 index things. Thus, -1 since Payout starts at 1st place
                        if i >= self.field_size:
                            break
                        self.payout_structure[i - 1] = float(
                            row["payout"].split(".")[0].replace(",", "")
                        )
                # single-position payouts
                else:
                    if int(row["place"]) >= self.field_size:
                        break
                    self.payout_structure[int(row["place"]) - 1] = float(
                        row["payout"].split(".")[0].replace(",", "")
                    )
        # print(self.payout_structure)

    def load_correlation_rules(self):
        if len(self.correlation_rules.keys()) > 0:
            for c in self.correlation_rules.keys():
                for k in self.player_dict:
                    if c.replace("-", "#").lower().strip() in self.player_dict[k].values():
                        for v in self.correlation_rules[c].keys():
                            self.player_dict[k]['Correlations'][v] = self.correlation_rules[c][v]

    # Load config from file
    def load_config(self):
        with open(
                os.path.join(os.path.dirname(__file__), "../config.json"),
                encoding="utf-8-sig",
        ) as json_file:
            self.config = json.load(json_file)

    # Load projections from file
    def load_projections(self, path):
        # Read projections into a dictionary
        with open(path, encoding="utf-8-sig") as file:
            reader = csv.DictReader(self.lower_first(file))
            for row in reader:
                player_name = row["name"].replace("-", "#").lower().strip()
                fpts = float(row["fpts"])
                position = [pos for pos in row['position'].split('/')]
                position.sort()
                # if qb not in position add flex and S-FLEX
                if 'QB' not in position:
                    position.append('FLEX')
                    position.append('S-FLEX')
                # if QB is in position add S-FLEX
                else:
                    position.append('S-FLEX')
                pos = position[0]
                if row['stddev'] == '':
                    if pos == 'QB':
                        stddev = fpts * self.default_qb_var
                    else:
                        stddev = fpts * self.default_skillpos_var
                else:
                    stddev = float(row["stddev"])
                # check if ceiling exists in row columns
                if row['ceiling']:
                    if row['ceiling'] == '':
                        ceil = float(row['fpts']) + stddev
                    else:
                        ceil = float(row['ceiling'])
                else:
                    ceil = float(row['fpts']) + stddev
                if row['salary']:
                    sal = int(row['salary'].replace(",", ""))
                if pos == 'QB':
                    corr = {'QB': 1, 'RB': 0.08, 'WR': 0.62, 'Opp QB': 0.24, 'Opp RB': 0.04,
                            'Opp WR': 0.19}
                elif pos == 'RB':
                    corr = {'QB': 0.08, 'RB': 1, 'WR': -0.09, 'Opp QB': 0.04, 'Opp RB': -0.08,
                            'Opp WR': 0.01}
                elif pos == 'WR':
                    corr = {'QB': 0.62, 'RB': -0.09, 'WR': 1, 'Opp QB': 0.19, 'Opp RB': 0.01,
                            'Opp WR': 0.16}
                team = row['team']
                # Removing the next few lines for now. Maybe add back if needed
                #if team == 'LA':
                #    team = 'LAR'
                #if self.site == 'fd':
                #    if team == 'JAX':
                #        team = 'JAC'
                pos_str = str(position)
                player_data = {
                    "Fpts": fpts,
                    "Position": position,
                    "Name": player_name,
                    "Team": team,
                    "Opp": '',
                    "ID": '',
                    "Salary": int(row["salary"].replace(",", "")),
                    "StdDev": stddev,
                    "Ceiling": ceil,
                    "Ownership": float(row["own%"]),
                    "Correlations": corr,
                    "In Lineup": False
                }

                # Check if player is in player_dict and get Opp, ID
                if (player_name, pos_str, team) in self.player_dict:
                    player_data["Opp"] = self.player_dict[(player_name, pos_str, team)].get("Opp", '')
                    player_data["ID"] = self.player_dict[(player_name, pos_str, team)].get("ID", '')

                self.player_dict[(player_name, pos_str, team)] = player_data
                self.teams_dict[team].append(player_data)  # Add player data to their respective team

    def load_team_stacks(self):
        # Initialize a dictionary to hold QB ownership by team
        qb_ownership_by_team = {}

        for p in self.player_dict:
            # Check if player is a QB
            if 'QB' in self.player_dict[p]['Position']:
                # Fetch the team of the QB
                team = self.player_dict[p]['Team']

                # Convert the ownership percentage string to a float and divide by 100
                own_percentage = float(self.player_dict[p]["Ownership"]) / 100

                # Add the ownership to the accumulated ownership for the team
                if team in qb_ownership_by_team:
                    qb_ownership_by_team[team] += own_percentage
                else:
                    qb_ownership_by_team[team] = own_percentage

        # Now, update the stacks_dict with the QB ownership by team
        for team, own_percentage in qb_ownership_by_team.items():
            self.stacks_dict[team] = own_percentage

    def extract_id(self, cell_value):
        if "(" in cell_value and ")" in cell_value:
            return cell_value.split("(")[1].replace(")", "")
        else:
            return cell_value

    def load_lineups_from_file(self):
        print("loading lineups")
        i = 0
        path = os.path.join(
            os.path.dirname(__file__),
            "../{}_data/{}".format(self.site, "tournament_lineups.csv"),
        )
        with open(path) as file:
            reader = pd.read_csv(file)
            lineup = []
            j = 0
            for i, row in reader.iterrows():
                # print(row)
                if i == self.field_size:
                    break
                lineup = [self.extract_id(str(row[j])) for j in range(9)]
                # storing if this lineup was made by an optimizer or with the generation process in this script
                error = False
                for l in lineup:
                    ids = [self.player_dict[k]['ID'] for k in self.player_dict]
                    if l not in ids:
                        print("lineup {} is missing players {}".format(i, l))
                        if l in self.id_name_dict:
                            print(self.id_name_dict[l])
                        error = True
                if len(lineup) < 8:
                    print("lineup {} is missing players".format(i))
                    continue
                # storing if this lineup was made by an optimizer or with the generation process in this script
                error = False
                for l in lineup:
                    ids = [self.player_dict[k]['ID'] for k in self.player_dict]
                    if l not in ids:
                        print("lineup {} is missing players {}".format(i, l))
                        if l in self.id_name_dict:
                            print(self.id_name_dict[l])
                        error = True
                if len(lineup) < 8:
                    print("lineup {} is missing players".format(i))
                    continue
                if not error:
                    # reshuffle lineup to match temp_roster_construction
                    temp_roster_construction = ['S-FLEX', 'QB', 'RB', 'RB', 'WR', 'WR', 'WR', 'FLEX']
                    shuffled_lu = []

                    id_to_player_dict = {v["ID"]: v for k, v in self.player_dict.items()}
                    lineup_copy = lineup.copy()
                    position_counts = {'S-FLEX': 0, 'QB': 0, 'RB': 0, 'WR': 0, 'FLEX': 0}
                    z = 0

                    while z < 8:
                        for t in temp_roster_construction:
                            if position_counts[t] < temp_roster_construction.count(t):
                                for l in lineup_copy:
                                    player_info = id_to_player_dict.get(l)
                                    if player_info and t in player_info['Position']:
                                        shuffled_lu.append(l)
                                        lineup_copy.remove(l)
                                        position_counts[t] += 1
                                        z += 1
                                        if z == 8:
                                            break
                            if z == 8:
                                break
                    self.field_lineups[j] = {
                        "Lineup": shuffled_lu,
                        "Wins": 0,
                        "Top10": 0,
                        "ROI": 0,
                        "Cashes": 0,
                        "Type": "input",
                    }
                    j += 1
        print("loaded {} lineups".format(j))
        # print(self.field_lineups)

    @staticmethod
    def generate_lineups(
            lu_num,
            ids,
            in_lineup,
            pos_matrix,
            ownership,
            salary_floor,
            salary_ceiling,
            optimal_score,
            salaries,
            projections,
            max_pct_off_optimal,
            teams,
            opponents,
            team_stack,
            stack_len,
            overlap_limit,
            max_stack_len,
            matchups
    ):
        # new random seed for each lineup (without this there is a ton of dupes)
        np.random.seed(lu_num)
        lus = {}
        # make sure nobody is already showing up in a lineup
        if sum(in_lineup) != 0:
            in_lineup.fill(0)
        reject = True
        iteration_count = 0
        issue = ''
        complete = ''
        # print(lu_num, ' started',  team_stack, max_stack_len)
        while reject:
            iteration_count += 1
            if team_stack == '':
                salary = 0
                proj = 0
                if sum(in_lineup) != 0:
                    in_lineup.fill(0)
                lineup = []
                player_teams = []
                def_opps = []
                players_opposing_def = 0
                lineup_matchups = []
                k = 0
                for pos in pos_matrix.T:
                    if k < 1:
                        # check for players eligible for the position and make sure they arent in a lineup, returns a list of indices of available player
                        valid_players = np.where((pos > 0) & (in_lineup == 0))
                        # grab names of players eligible
                        plyr_list = ids[valid_players]
                        # create np array of probability of being selected based on ownership and who is eligible at the position
                        prob_list = ownership[valid_players]
                        prob_list = prob_list / prob_list.sum()
                        try:
                            choice = np.random.choice(a=plyr_list, p=prob_list)
                        except:
                            print(plyr_list, prob_list)
                        choice_idx = np.where(ids == choice)[0]
                        lineup.append(str(choice))
                        in_lineup[choice_idx] = 1
                        salary += salaries[choice_idx]
                        proj += projections[choice_idx]
                        def_opp = opponents[choice_idx][0]
                        lineup_matchups.append(matchups[choice_idx[0]])
                    if k >= 1:
                        if players_opposing_def < overlap_limit:
                            valid_players = np.where((pos > 0) & (in_lineup == 0))
                            # grab names of players eligible
                            plyr_list = ids[valid_players]
                            # create np array of probability of being seelcted based on ownership and who is eligible at the position
                            prob_list = ownership[valid_players]
                            prob_list = prob_list / prob_list.sum()
                            choice = np.random.choice(a=plyr_list, p=prob_list)
                            choice_idx = np.where(ids == choice)[0]
                            lineup.append(str(choice))
                            in_lineup[choice_idx] = 1
                            salary += salaries[choice_idx]
                            proj += projections[choice_idx]
                            player_teams.append(teams[choice_idx][0])
                            lineup_matchups.append(matchups[choice_idx[0]])
                            if teams[choice_idx][0] == def_opp:
                                players_opposing_def += 1
                        else:
                            valid_players = np.where((pos > 0) & (in_lineup == 0) & (teams != def_opp))
                            plyr_list = ids[valid_players]
                            # create np array of probability of being seelcted based on ownership and who is eligible at the position
                            prob_list = ownership[valid_players]
                            prob_list = prob_list / prob_list.sum()
                            choice = np.random.choice(a=plyr_list, p=prob_list)
                            choice_idx = np.where(ids == choice)[0]
                            lineup.append(str(choice))
                            in_lineup[choice_idx] = 1
                            salary += salaries[choice_idx]
                            proj += projections[choice_idx]
                            player_teams.append(teams[choice_idx][0])
                            lineup_matchups.append(matchups[choice_idx[0]])
                            if teams[choice_idx][0] == def_opp:
                                players_opposing_def += 1
                    k += 1
                    # Must have a reasonable salary
                if salary >= salary_floor and salary <= salary_ceiling:
                    # Must have a reasonable projection (within 60% of optimal) **people make a lot of bad lineups
                    reasonable_projection = optimal_score - (
                            max_pct_off_optimal * optimal_score
                    )
                    if proj >= reasonable_projection:
                        if len(set(lineup_matchups)) > 1:
                            if len(set(lineup)) != 9:
                                print('non stack lineup dupes', plyr_stack_indices, str(lu_num),
                                      salaries[plyr_stack_indices], lineup, stack_len, team_stack, x)
                            reject = False
                            lus[lu_num] = {
                                "Lineup": lineup,
                                "Wins": 0,
                                "Top10": 0,
                                "ROI": 0,
                                "Cashes": 0,
                                "Type": "generated_nostack",
                            }
                            # complete = 'completed'
                            # print(str(lu_num) + ' ' + complete)
            else:
                salary = 0
                proj = 0
                if sum(in_lineup) != 0:
                    in_lineup.fill(0)
                player_teams = []
                def_opps = []
                lineup_matchups = []
                filled_pos = np.zeros(shape=pos_matrix.shape[1])
                team_stack_len = 0
                k = 0
                stack = True
                lineup = np.zeros(shape=pos_matrix.shape[1]).astype(str)
                valid_team = np.where(teams == team_stack)[0]
                # select qb
                qb = np.unique(valid_team[np.where(pos_matrix[valid_team, 1] > 0)[0]])[0]
                salary += salaries[qb]
                proj += projections[qb]
                # print(salary)
                team_stack_len += 1
                lineup[1] = ids[qb]
                in_lineup[qb] = 1
                lineup_matchups.append(matchups[qb])
                valid_players = np.unique(valid_team[np.where(pos_matrix[valid_team, 4:8] > 0)[0]])
                players_opposing_def = 0
                plyr_list = ids[valid_players]
                prob_list = ownership[valid_players]
                prob_list = prob_list / prob_list.sum()
                while stack:
                    try:
                        choices = np.random.choice(a=plyr_list, p=prob_list, size=stack_len, replace=False)
                        if len(set(choices)) != len(choices):
                            print('choice dupe', plyr_stack_indices, str(lu_num), salaries[plyr_stack_indices], lineup,
                                  stack_len, team_stack, x)
                    except:
                        stack = False
                        continue
                    plyr_stack_indices = np.where(np.in1d(ids, choices))[0]
                    x = 0
                    for p in plyr_stack_indices:
                        player_placed = False
                        for l in np.where(pos_matrix[p] > 0)[0]:
                            if lineup[l] == '0.0':
                                lineup[l] = ids[p]
                                lineup_matchups.append(matchups[p])
                                x += 1
                                player_placed = True
                                break
                            if player_placed:
                                break
                    # print(plyr_stack_indices, str(lu_num), salaries[plyr_stack_indices], lineup, stack_len, x)
                    if x == stack_len:
                        in_lineup[plyr_stack_indices] = 1
                        salary += sum(salaries[plyr_stack_indices])
                        # rint(salary)
                        proj += sum(projections[plyr_stack_indices])
                        # print(proj)
                        team_stack_len += stack_len
                        x = 0
                        stack = False
                    else:
                        stack = False
                # print(sum(in_lineup), stack_len)
                for ix, (l, pos) in enumerate(zip(lineup, pos_matrix.T)):
                    if l == '0.0':
                        if k < 1:
                            valid_players = np.where((pos > 0) & (in_lineup == 0) & (opponents != team_stack))
                            # grab names of players eligible
                            plyr_list = ids[valid_players]
                            # create np array of probability of being selected based on ownership and who is eligible at the position
                            prob_list = ownership[valid_players]
                            prob_list = prob_list / prob_list.sum()
                            # try:
                            choice = np.random.choice(a=plyr_list, p=prob_list)
                            # except:
                            #    print(k, pos)
                            choice_idx = np.where(ids == choice)[0]
                            in_lineup[choice_idx] = 1
                            lineup[ix] = str(choice)
                            salary += salaries[choice_idx]
                            proj += projections[choice_idx]
                            def_opp = opponents[choice_idx][0]
                            lineup_matchups.append(matchups[choice_idx[0]])
                            k += 1
                        elif k >= 1:
                            if players_opposing_def < overlap_limit:
                                valid_players = np.where((pos > 0) & (in_lineup == 0))
                                # grab names of players eligible
                                plyr_list = ids[valid_players]
                                # create np array of probability of being seelcted based on ownership and who is eligible at the position
                                prob_list = ownership[valid_players]
                                prob_list = prob_list / prob_list.sum()
                                choice = np.random.choice(a=plyr_list, p=prob_list)
                                choice_idx = np.where(ids == choice)[0]
                                lineup[ix] = str(choice)
                                in_lineup[choice_idx] = 1
                                salary += salaries[choice_idx]
                                proj += projections[choice_idx]
                                player_teams.append(teams[choice_idx][0])
                                lineup_matchups.append(matchups[choice_idx[0]])
                                if teams[choice_idx][0] == def_opp:
                                    players_opposing_def += 1
                                if teams[choice_idx][0] == team_stack:
                                    team_stack_len += 1
                            else:
                                valid_players = np.where((pos > 0) & (in_lineup == 0) & (teams != def_opp))
                                plyr_list = ids[valid_players]
                                # create np array of probability of being seelcted based on ownership and who is eligible at the position
                                prob_list = ownership[valid_players]
                                prob_list = prob_list / prob_list.sum()
                                choice = np.random.choice(a=plyr_list, p=prob_list)
                                choice_idx = np.where(ids == choice)[0]
                                lineup[ix] = str(choice)
                                in_lineup[choice_idx] = 1
                                salary += salaries[choice_idx]
                                proj += projections[choice_idx]
                                player_teams.append(teams[choice_idx][0])
                                lineup_matchups.append(matchups[choice_idx[0]])
                                if teams[choice_idx][0] == def_opp:
                                    players_opposing_def += 1
                                if teams[choice_idx][0] == team_stack:
                                    team_stack_len += 1
                            k += 1
                    else:
                        k += 1
                # Must have a reasonable salary
                if team_stack_len >= stack_len:
                    if salary >= salary_floor and salary <= salary_ceiling:
                        # loosening reasonable projection constraint for team stacks
                        reasonable_projection = optimal_score - (
                                (max_pct_off_optimal * 1.25) * optimal_score
                        )
                        if proj >= reasonable_projection:
                            if len(set(lineup_matchups)) > 1:
                                reject = False
                                lus[lu_num] = {
                                    "Lineup": lineup,
                                    "Wins": 0,
                                    "Top10": 0,
                                    "ROI": 0,
                                    "Cashes": 0,
                                    "Type": "generated_stack",
                                }
                                if len(set(lineup)) != 9:
                                    print('stack lineup dupes', lu_num, plyr_stack_indices, str(lu_num),
                                          salaries[plyr_stack_indices], lineup, stack_len, team_stack, x)
                #                 complete = 'completed'
                #                 print(str(lu_num) + ' ' + complete)
                #             else:
                #                 print(str(lu_num) + ' matchups' + str(lineup_matchups))
                #                 print(lu_num, team_stack, overlap_limit, max_stack_len, issue, iteration_count)
                #         else:
                #             print(str(lu_num) + ' proj' + str(reasonable_projection) + str(optimal_score))
                #             print(lu_num, team_stack, overlap_limit, max_stack_len, issue, iteration_count)
                #     else:
                #         print(str(lu_num) + ' salary' + str(salary))
                #         print(lu_num, team_stack, overlap_limit, max_stack_len, issue, iteration_count)
                # else:
                #     print(str(lu_num) + ' stack' + str(team_stack_len) + str(stack_len))
                #     print(lu_num, team_stack, overlap_limit, max_stack_len, issue, iteration_count)
        return lus

    def generate_field_lineups(self):
        diff = self.field_size - len(self.field_lineups)
        if diff <= 0:
            print(
                "supplied lineups >= contest field size. only retrieving the first "
                + str(self.field_size)
                + " lineups"
            )
        else:
            print('Generating ' + str(diff) + ' lineups.')
            ids = []
            ownership = []
            salaries = []
            projections = []
            positions = []
            teams = []
            opponents = []
            matchups = []
            # put def first to make it easier to avoid overlap
            temp_roster_construction = ['S-FLEX', 'QB', 'RB', 'RB', 'WR', 'WR', 'WR', 'FLEX']
            for k in self.player_dict.keys():
                if 'Team' not in self.player_dict[k].keys():
                    print(self.player_dict[k]['Name'], ' name mismatch between projections and player ids!')
                ids.append(self.player_dict[k]['ID'])
                ownership.append(self.player_dict[k]['Ownership'])
                salaries.append(self.player_dict[k]['Salary'])
                if self.player_dict[k]['Fpts'] >= self.projection_minimum:
                    projections.append(self.player_dict[k]['Fpts'])
                else:
                    projections.append(0)
                teams.append(self.player_dict[k]['Team'])
                opponents.append(self.player_dict[k]['Opp'])
                matchups.append(self.player_dict[k]['Matchup'])
                pos_list = []
                for pos in temp_roster_construction:
                    if pos in self.player_dict[k]['Position']:
                        pos_list.append(1)
                    else:
                        pos_list.append(0)
                positions.append(np.array(pos_list))
            in_lineup = np.zeros(shape=len(ids))
            ownership = np.array(ownership)
            salaries = np.array(salaries)
            projections = np.array(projections)
            pos_matrix = np.array(positions)
            ids = np.array(ids)
            optimal_score = self.optimal_score
            salary_floor = self.min_lineup_salary
            salary_ceiling = self.salary
            max_pct_off_optimal = self.max_pct_off_optimal
            stack_usage = self.pct_field_using_stacks
            teams = np.array(teams)
            opponents = np.array(opponents)
            overlap_limit = self.overlap_limit
            problems = []
            stacks = np.random.binomial(n=1, p=self.pct_field_using_stacks, size=diff)
            stack_len = np.random.choice(a=[1, 2], p=[1 - self.pct_field_double_stacks, self.pct_field_double_stacks],
                                         size=diff)
            max_stack_len = 2
            a = list(self.stacks_dict.keys())
            p = np.array(list(self.stacks_dict.values()))
            probs = p / sum(p)
            stacks = stacks.astype(str)
            for i in range(len(stacks)):
                if stacks[i] == '1':
                    choice = random.choices(a, weights=probs, k=1)
                    stacks[i] = choice[0]
                else:
                    stacks[i] = ''
            # creating tuples of the above np arrays plus which lineup number we are going to create
            # q = 0
            # for k in self.player_dict.keys():
            # if self.player_dict[k]['Team'] == stacks[0]:
            #    print(k, self.player_dict[k]['ID'])
            #    print(positions[q])
            # q += 1
            for i in range(diff):
                lu_tuple = (
                i, ids, in_lineup, pos_matrix, ownership, salary_floor, salary_ceiling, optimal_score, salaries,
                projections, max_pct_off_optimal, teams, opponents, stacks[i], stack_len[i], overlap_limit,
                max_stack_len, matchups)
                problems.append(lu_tuple)
            # print(problems[0])
            # print(stacks)
            start_time = time.time()
            with mp.Pool() as pool:
                output = pool.starmap(self.generate_lineups, problems)
                print(
                    "number of running processes =",
                    pool.__dict__["_processes"]
                    if (pool.__dict__["_state"]).upper() == "RUN"
                    else None,
                )
                pool.close()
                pool.join()
            print('pool closed')
            if len(self.field_lineups) == 0:
                new_keys = list(range(0, self.field_size))
            else:
                new_keys = list(
                    range(max(self.field_lineups.keys()) + 1, self.field_size)
                )
            nk = new_keys[0]
            for i, o in enumerate(output):
                if nk in self.field_lineups.keys():
                    print("bad lineups dict, please check dk_data files")
                self.field_lineups[nk] = o[i]
                nk += 1
            end_time = time.time()
            print("lineups took " + str(end_time - start_time) + " seconds")
            print(str(diff) + " field lineups successfully generated")
            # print(self.field_lineups)

    def calc_gamma(self, mean, sd):
        alpha = (mean / sd) ** 2
        beta = sd ** 2 / mean
        return alpha, beta

    @staticmethod
    def run_simulation_for_game(team1_id, team1, team2_id, team2, qb_samples_dict, num_iterations, roster_construction):
        # Define correlations between positions

        def get_corr_value(player1, player2):
            # If players are on the same team and have the same position
            if player1['Team'] == player2['Team'] and player1['Position'][0] == player2['Position'][0]:
                return -0.25

            if player1['Team'] != player2['Team']:
                player_2_pos = 'Opp ' + str(player2['Position'][0])
            else:
                player_2_pos = player2['Position'][0]

            # Fetch correlation value based on player1's primary position for player2's primary position
            return player1['Correlations'][player_2_pos]

        def build_covariance_matrix(players):
            N = len(players)
            matrix = [[0 for _ in range(N)] for _ in range(N)]
            corr_matrix = [[0 for _ in range(N)] for _ in range(N)]

            for i in range(N):
                for j in range(N):
                    if i == j:
                        matrix[i][j] = players[i]['StdDev'] ** 2  # Variance on the diagonal
                        corr_matrix[i][j] = 1
                    else:
                        matrix[i][j] = get_corr_value(players[i], players[j]) * players[i]['StdDev'] * players[j][
                            'StdDev']
                        corr_matrix[i][j] = get_corr_value(players[i], players[j])
            return matrix, corr_matrix

        def ensure_positive_semidefinite(matrix):
            eigs = np.linalg.eigvals(matrix)
            if np.any(eigs < 0):
                jitter = abs(min(eigs)) + 1e-6  # a small value
                matrix += np.eye(len(matrix)) * jitter
            return matrix

        game = team1 + team2
        covariance_matrix, corr_matrix = build_covariance_matrix(game)
        # print(team1_id, team2_id)
        # print(corr_matrix)
        corr_matrix = np.array(corr_matrix)

        # Given eigenvalues and eigenvectors from previous code
        eigenvalues, eigenvectors = np.linalg.eigh(covariance_matrix)

        # Set negative eigenvalues to zero
        eigenvalues[eigenvalues < 0] = 0

        # Reconstruct the matrix
        covariance_matrix = eigenvectors.dot(np.diag(eigenvalues)).dot(eigenvectors.T)

        try:
            samples = multivariate_normal.rvs(mean=[player['Fpts'] for player in game], cov=covariance_matrix,
                                              size=num_iterations)
        except:
            print(team1_id, team2_id, 'bad matrix')

        player_samples = []
        for i, player in enumerate(game):
            if 'QB' in player['Position']:
                sample = samples[:, i]
            else:
                sample = samples[:, i]
            # if player['Team'] in ['LAR','SEA']:
            #     print(player['Name'], player['Fpts'], player['StdDev'], sample, np.mean(sample), np.std(sample))
            player_samples.append(sample)

        temp_fpts_dict = {}
        # print(team1_id, team2_id, len(game), uniform_samples.T.shape, len(player_samples), covariance_matrix.shape )

        for i, player in enumerate(game):
            temp_fpts_dict[player['ID']] = player_samples[i]

        # fig, (ax1, ax2, ax3,ax4) = plt.subplots(4, figsize=(15, 25))
        # fig.tight_layout(pad=5.0)

        # for i, player in enumerate(game):
        #     sns.kdeplot(player_samples[i], ax=ax1, label=player['Name'])

        # ax1.legend(loc='upper right', fontsize=14)
        # ax1.set_xlabel('Fpts', fontsize=14)
        # ax1.set_ylabel('Density', fontsize=14)
        # ax1.set_title(f'Team {team1_id}{team2_id} Distributions', fontsize=14)
        # ax1.tick_params(axis='both', which='both', labelsize=14)

        # y_min, y_max = ax1.get_ylim()
        # ax1.set_ylim(y_min, y_max*1.1)

        # ax1.set_xlim(-5, 50)

        # # # Sorting players and correlating their data
        # player_names = [f"{player['Name']} ({player['Position']})" if player['Position'] is not None else f"{player['Name']} (P)" for player in game]

        # # # Ensuring the data is correctly structured as a 2D array
        # sorted_samples_array = np.array(player_samples)
        # if sorted_samples_array.shape[0] < sorted_samples_array.shape[1]:
        #     sorted_samples_array = sorted_samples_array.T

        # correlation_matrix = pd.DataFrame(np.corrcoef(sorted_samples_array.T), columns=player_names, index=player_names)

        # sns.heatmap(correlation_matrix, annot=True, ax=ax2, cmap='YlGnBu', cbar_kws={"shrink": .5})
        # ax2.set_title(f'Correlation Matrix for Game {team1_id}{team2_id}', fontsize=14)

        # original_corr_matrix = pd.DataFrame(corr_matrix, columns=player_names, index=player_names)
        # sns.heatmap(original_corr_matrix, annot=True, ax=ax3, cmap='YlGnBu', cbar_kws={"shrink": .5})
        # ax3.set_title(f'Original Correlation Matrix for Game {team1_id}{team2_id}', fontsize=14)

        # cov_matrix = pd.DataFrame(covariance_matrix, columns=player_names, index=player_names)
        # sns.heatmap(cov_matrix, annot=True, ax=ax4, cmap='YlGnBu', cbar_kws={"shrink": .5})
        # ax4.set_title(f'Original Covariance Matrix for Game {team1_id}{team2_id}', fontsize=14)

        # plt.savefig(f'output/Team_{team1_id}{team2_id}_Distributions_Correlation.png', bbox_inches='tight')
        # plt.close()

        return temp_fpts_dict

    def run_tournament_simulation(self):
        print("Running " + str(self.num_iterations) + " simulations")
        for f in self.field_lineups:
            if len(self.field_lineups[f]['Lineup']) != 9:
                print('bad lineup', f, self.field_lineups[f])

        start_time = time.time()
        temp_fpts_dict = {}
        qb_samples_dict = {}  # keep track of already simmed quarterbacks
        size = self.num_iterations
        game_simulation_params = []
        for m in self.matchups:
            game_simulation_params.append((m[0], self.teams_dict[m[0]], m[1], self.teams_dict[m[1]], qb_samples_dict,
                                           self.num_iterations, self.roster_construction))
        with mp.Pool() as pool:
            results = pool.starmap(self.run_simulation_for_game, game_simulation_params)

        for res in results:
            temp_fpts_dict.update(res)

        # generate arrays for every sim result for each player in the lineup and sum
        fpts_array = np.zeros(shape=(self.field_size, self.num_iterations))
        # converting payout structure into an np friendly format, could probably just do this in the load contest function
        payout_array = np.array(list(self.payout_structure.values()))
        # subtract entry fee
        payout_array = payout_array - self.entry_fee
        l_array = np.full(shape=self.field_size - len(payout_array), fill_value=-self.entry_fee)
        payout_array = np.concatenate((payout_array, l_array))
        for index, values in self.field_lineups.items():
            try:
                fpts_sim = sum([temp_fpts_dict[player] for player in values["Lineup"]])
            except KeyError:
                for player in values["Lineup"]:
                    if player not in temp_fpts_dict.keys():
                        for k, v in self.player_dict.items():
                            if v['ID'] == player:
                                print(k, v)
                # print('cant find player in sim dict', values["Lineup"], temp_fpts_dict.keys())
            # store lineup fpts sum in 2d np array where index (row) corresponds to index of field_lineups and columns are the fpts from each sim
            fpts_array[index] = fpts_sim
        ranks = np.argsort(fpts_array, axis=0)[::-1]
        # count wins, top 10s vectorized
        wins, win_counts = np.unique(ranks[0, :], return_counts=True)
        t10, t10_counts = np.unique(ranks[0:9:], return_counts=True)
        roi = payout_array[np.argsort(ranks, axis=0)].sum(axis=1)
        # summing up ach lineup, probably a way to v)ectorize this too (maybe just turning the field dict into an array too)
        for idx in self.field_lineups.keys():
            # Winning
            if idx in wins:
                self.field_lineups[idx]["Wins"] += win_counts[np.where(wins == idx)][0]
            # Top 10
            if idx in t10:
                self.field_lineups[idx]["Top10"] += t10_counts[np.where(t10 == idx)][0]
            # can't figure out how to get roi for each lineup index without iterating and iterating is slow
            if self.use_contest_data:
                self.field_lineups[idx]["ROI"] += roi[idx]
        end_time = time.time()
        diff = end_time - start_time
        print(str(self.num_iterations) + " tournament simulations finished in " + str(diff) + "seconds. Outputting.")

    def output(self):
        unique = {}
        for index, x in self.field_lineups.items():
            # if index == 0:
            #    print(x)
            lu_type = x["Type"]
            salary = 0
            fpts_p = 0
            ceil_p = 0
            own_p = []
            lu_names = []
            lu_teams = []
            players_vs_def = 0
            def_opps = []
            for id in x["Lineup"]:
                for k, v in self.player_dict.items():
                    if v["ID"] == id:
                        if 'DST' in v["Position"]:
                            def_opps.append(v['Opp'])
            for id in x["Lineup"]:
                for k, v in self.player_dict.items():
                    if v["ID"] == id:
                        salary += v["Salary"]
                        fpts_p += v["Fpts"]
                        ceil_p += v["Ceiling"]
                        own_p.append(v["Ownership"] / 100)
                        lu_names.append(v["Name"])
                        if 'DST' not in v["Position"]:
                            lu_teams.append(v['Team'])
                            if v['Team'] in def_opps:
                                players_vs_def += 1
                        continue
            counter = collections.Counter(lu_teams)
            stacks = counter.most_common(2)
            own_p = np.prod(own_p)
            win_p = round(x["Wins"] / self.num_iterations * 100, 2)
            top10_p = round(x["Top10"] / self.num_iterations * 100, 2)
            cash_p = round(x["Cashes"] / self.num_iterations * 100, 2)
            if self.site == "dk":
                if self.use_contest_data:
                    roi_p = round(
                        x["ROI"] / self.entry_fee / self.num_iterations * 100, 2
                    )
                    roi_round = round(x["ROI"] / self.num_iterations, 2)
                    lineup_str = "{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{},{},${},{}%,{}%,{}%,{},${},{},{},{},{}".format(
                        lu_names[1].replace("#", "-"),
                        x["Lineup"][1],
                        lu_names[2].replace("#", "-"),
                        x["Lineup"][2],
                        lu_names[3].replace("#", "-"),
                        x["Lineup"][3],
                        lu_names[4].replace("#", "-"),
                        x["Lineup"][4],
                        lu_names[5].replace("#", "-"),
                        x["Lineup"][5],
                        lu_names[6].replace("#", "-"),
                        x["Lineup"][6],
                        lu_names[7].replace("#", "-"),
                        x["Lineup"][7],
                        lu_names[0].replace("#", "-"),
                        x["Lineup"][0],
                        fpts_p,
                        ceil_p,
                        salary,
                        win_p,
                        top10_p,
                        roi_p,
                        own_p,
                        roi_round,
                        str(stacks[0][0]) + ' ' + str(stacks[0][1]),
                        str(stacks[1][0]) + ' ' + str(stacks[1][1]),
                        players_vs_def,
                        lu_type
                    )
                else:
                    lineup_str = "{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{} ({}),{},{},{},{}%,{}%,{}%,{},{},{},{}".format(
                        lu_names[1].replace("#", "-"),
                        x["Lineup"][1],
                        lu_names[2].replace("#", "-"),
                        x["Lineup"][2],
                        lu_names[3].replace("#", "-"),
                        x["Lineup"][3],
                        lu_names[4].replace("#", "-"),
                        x["Lineup"][4],
                        lu_names[5].replace("#", "-"),
                        x["Lineup"][5],
                        lu_names[6].replace("#", "-"),
                        x["Lineup"][6],
                        lu_names[7].replace("#", "-"),
                        x["Lineup"][7],
                        lu_names[0].replace("#", "-"),
                        x["Lineup"][0],
                        fpts_p,
                        ceil_p,
                        salary,
                        win_p,
                        top10_p,
                        own_p,
                        str(stacks[0][0]) + ' ' + str(stacks[0][1]),
                        str(stacks[1][0]) + ' ' + str(stacks[1][1]),
                        players_vs_def,
                        lu_type
                    )
            elif self.site == "fd":
                if self.use_contest_data:
                    roi_p = round(
                        x["ROI"] / self.entry_fee / self.num_iterations * 100, 2
                    )
                    roi_round = round(x["ROI"] / self.num_iterations, 2)
                    lineup_str = "{}:{},{}:{},{}:{},{}:{},{}:{},{}:{},{}:{},{}:{},{},{},{},{}%,{}%,{}%,{},${},{},{},{},{}".format(
                        lu_names[1].replace("#", "-"),
                        x["Lineup"][1],
                        lu_names[2].replace("#", "-"),
                        x["Lineup"][2],
                        lu_names[3].replace("#", "-"),
                        x["Lineup"][3],
                        lu_names[4].replace("#", "-"),
                        x["Lineup"][4],
                        lu_names[5].replace("#", "-"),
                        x["Lineup"][5],
                        lu_names[6].replace("#", "-"),
                        x["Lineup"][6],
                        lu_names[7].replace("#", "-"),
                        x["Lineup"][7],
                        lu_names[0].replace("#", "-"),
                        x["Lineup"][0],
                        fpts_p,
                        ceil_p,
                        salary,
                        win_p,
                        top10_p,
                        roi_p,
                        own_p,
                        roi_round,
                        str(stacks[0][0]) + ' ' + str(stacks[0][1]),
                        str(stacks[1][0]) + ' ' + str(stacks[1][1]),
                        players_vs_def,
                        lu_type
                    )
                else:
                    lineup_str = "{}:{},{}:{},{}:{},{}:{},{}:{},{}:{},{}:{},{}:{},{},{},{},{}%,{}%,{},{},{},{},{}".format(
                        lu_names[1].replace("#", "-"),
                        x["Lineup"][1],
                        lu_names[2].replace("#", "-"),
                        x["Lineup"][2],
                        lu_names[3].replace("#", "-"),
                        x["Lineup"][3],
                        lu_names[4].replace("#", "-"),
                        x["Lineup"][4],
                        lu_names[5].replace("#", "-"),
                        x["Lineup"][5],
                        lu_names[6].replace("#", "-"),
                        x["Lineup"][6],
                        lu_names[7].replace("#", "-"),
                        x["Lineup"][7],
                        lu_names[0].replace("#", "-"),
                        x["Lineup"][0],
                        fpts_p,
                        ceil_p,
                        salary,
                        win_p,
                        top10_p,
                        own_p,
                        str(stacks[0][0]) + ' ' + str(stacks[0][1]),
                        str(stacks[1][0]) + ' ' + str(stacks[1][1]),
                        players_vs_def,
                        lu_type
                    )
            unique[index] = lineup_str

        out_path = os.path.join(
            os.path.dirname(__file__),
            "../output/{}_gpp_sim_lineups_{}_{}.csv".format(
                self.site, self.field_size, self.num_iterations
            ),
        )
        with open(out_path, "w") as f:
            if self.site == "dk":
                if self.use_contest_data:
                    f.write(
                        "QB,RB,RB,WR,WR,WR,FLEX,S-FLEX,Fpts Proj,Ceiling,Salary,Win %,Top 10%,ROI%,Proj. Own. Product,Avg. Return,Stack1 Type,Stack2 Type,Players vs DST,Lineup Type\n"
                    )
                else:
                    f.write(
                        "QB,RB,RB,WR,WR,WR,FLEX,S-FLEX,Fpts Proj,Ceiling,Salary,Win %,Top 10%, Proj. Own. Product,Stack1 Type,Stack2 Type,Players vs DST,Lineup Type\n"
                    )
            elif self.site == "fd":
                if self.use_contest_data:
                    f.write(
                        "QB,RB,RB,WR,WR,WR,FLEX,S-FLEX,Fpts Proj,Ceiling,Salary,Win %,Top 10%,ROI%,Proj. Own. Product,Avg. Return,Stack1 Type,Stack2 Type,Players vs DST,Lineup Type\n"
                    )
                else:
                    f.write(
                        "QB,RB,RB,WR,WR,WR,FLEX,S-FLEX,Fpts Proj,Ceiling,Salary,Win %,Top 10%,Proj. Own. Product,Stack1 Type,Stack2 Type,Players vs DST,Lineup Type\n"
                    )

            for fpts, lineup_str in unique.items():
                f.write("%s\n" % lineup_str)

        out_path = os.path.join(
            os.path.dirname(__file__),
            "../output/{}_gpp_sim_player_exposure_{}_{}.csv".format(
                self.site, self.field_size, self.num_iterations
            ),
        )
        with open(out_path, "w") as f:
            f.write("Player,Position,Team,Win%,Top10%,Sim. Own%,Proj. Own%,Avg. Return\n")
            unique_players = {}
            for val in self.field_lineups.values():
                for player in val["Lineup"]:
                    if player not in unique_players:
                        unique_players[player] = {
                            "Wins": val["Wins"],
                            "Top10": val["Top10"],
                            "In": 1,
                            "ROI": val["ROI"],
                        }
                    else:
                        unique_players[player]["Wins"] = (
                                unique_players[player]["Wins"] + val["Wins"]
                        )
                        unique_players[player]["Top10"] = (
                                unique_players[player]["Top10"] + val["Top10"]
                        )
                        unique_players[player]["In"] = unique_players[player]["In"] + 1
                        unique_players[player]["ROI"] = (
                                unique_players[player]["ROI"] + val["ROI"]
                        )

            for player, data in unique_players.items():
                field_p = round(data["In"] / self.field_size * 100, 2)
                win_p = round(data["Wins"] / self.num_iterations * 100, 2)
                top10_p = round(data["Top10"] / self.num_iterations / 10 * 100, 2)
                roi_p = round(data["ROI"] / data["In"] / self.num_iterations, 2)
                for k, v in self.player_dict.items():
                    if player == v["ID"]:
                        proj_own = v["Ownership"]
                        p_name = v["Name"]
                        position = "/".join(v.get("Position"))
                        team = v.get("Team")
                        break
                f.write(
                    "{},{},{},{}%,{}%,{}%,{}%,${}\n".format(
                        p_name.replace("#", "-"),
                        position,
                        team,
                        win_p,
                        top10_p,
                        field_p,
                        proj_own,
                        roi_p,
                    )
                )