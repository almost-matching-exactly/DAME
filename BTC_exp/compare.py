import pyodbc
import time
import pickle
import operator
from operator import itemgetter
from joblib import Parallel, delayed
from sklearn import linear_model
from sklearn.linear_model import Ridge
from sklearn.tree import DecisionTreeRegressor
from sklearn.model_selection import cross_val_score
from sqlalchemy import create_engine
import psycopg2
from sklearn.utils import shuffle
import sql
import pandas as pd
import numpy as np
import matplotlib 
import matplotlib.pyplot as plt
from decimal import *
import re
from functools import partial

#get matching result for collapsing FLAME    
with open('res/FLAME-col-result','rb') as f:
    data = pickle.load(f) 
match_list_col = data

cates = {}

for match in match_list_col: 
    if match is None:
        continue
    for group in match:
        index_list = group[2]
        mean = group[0]
        for idx in index_list:
            cates[idx] = mean

sorted_cates = sorted(cates.items(), key = operator.itemgetter(1))
#print(sorted_cates)


df = pd.read_csv('data/MyBTCData_R2.csv', index_col=0, parse_dates=True)
df = df.rename(columns={'BTC': 'treated', 'outcome_matrix$ANY_NDRU': 'outcome'})
df_treated = df.loc[:,'treated']
df = df.drop('treated',1)
df_outcome = df.loc[:,'outcome']
df = df.drop('outcome',1)
shape = df.shape 
row_num = shape[0]
col_num = shape[1]
df.columns = np.arange(col_num)
df.columns = df.columns.astype(str) 

#merge covariates and outcomes
df = pd.concat([df, df_treated, df_outcome], axis=1)  
for label in df:
    if label == 'outcome':
        df[label][df[label] == 0] = -1
df['outcome'] = df['outcome'].astype('object')        
df['matched'] = 0

df = df.reset_index()
df['index'] = df.index

"""
large_cate_data_idx = [22, 374, 353, 21, 116, 178, 32, 194, 192]
large_cate_people = df[df["index"].isin(large_cate_data_idx)]
print(large_cate_people)



small_cate_data_idx = [210, 68, 0, 341, 350, 209, 283, 342, 224, 262, 263, 354, 236, 228, 309, 176, 25, 252, 179, 62, 94, ]
small_cate_people = df[df["index"].isin(small_cate_data_idx)]
print(small_cate_people)
"""