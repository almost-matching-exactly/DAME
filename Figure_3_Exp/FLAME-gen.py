
# coding: utf-8

# In[46]:

import numpy as np
import pandas as pd
#import pyodbc
import pickle
import time
import itertools
from joblib import Parallel, delayed

from sklearn.metrics.pairwise import pairwise_distances
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.tree import DecisionTreeRegressor
from sklearn.metrics import mean_squared_error as MSE
from operator import itemgetter

import operator
from sklearn import linear_model

from sklearn.linear_model import Ridge
from sklearn.model_selection import cross_val_score
from sklearn.tree import DecisionTreeRegressor

from sqlalchemy import create_engine

from mpl_toolkits.mplot3d import Axes3D
import matplotlib.pyplot as plt

import numpy as np
import pandas as pd
import pickle
import time
import itertools
from joblib import Parallel, delayed
import matplotlib.pyplot as plt
from sklearn.metrics.pairwise import pairwise_distances
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.tree import DecisionTreeRegressor
from sklearn.metrics import mean_squared_error as MSE
from operator import itemgetter
import operator
from sklearn import linear_model
from sklearn.linear_model import Ridge
from sklearn.model_selection import cross_val_score
from sklearn.tree import DecisionTreeRegressor
from sqlalchemy import create_engine
from mpl_toolkits.mplot3d import Axes3D
import warnings; warnings.simplefilter('ignore')
from decimal import *
import random
from itertools import combinations
import re
from sklearn import linear_model
import statsmodels.formula.api as sm
from statsmodels.stats import anova
import pylab as pl
from multiprocessing import Pool
from functools import partial
import warnings
import pysal
from pysal.spreg.twosls import TSLS
import random

def construct_sec_order(arr):
    
    # an intermediate data generation function used for generating second order information
    
    second_order_feature = []
    num_cov_sec = len(arr[0])
    for a in arr:
        tmp = []
        for i in range(num_cov_sec):
            for j in range(i+1, num_cov_sec):
                tmp.append( a[i] * a[j] )
        second_order_feature.append(tmp)
        
    return np.array(second_order_feature)


# In[51]:

def data_generation(num_control, num_treated, num_cov_important, num_covs_unimportant, 
                            control_m = 0.1, treated_m = 0.9):
    
    # the data generating function that we will use. include second order information
    
    xc = np.random.binomial(1, 0.5, size=(num_control, num_cov_important))   # data for conum_treatedrol group
    xt = np.random.binomial(1, 0.5, size=(num_treated, num_cov_important))   # data for treatmenum_treated group
        
    errors1 = np.random.normal(0, 0.1, size=num_control)    # some noise
    errors2 = np.random.normal(0, 0.1, size=num_treated)    # some noise
    
    dense_bs_sign = np.random.choice([-1,1], num_cov_important)
    #dense_bs = [ np.random.normal(dense_bs_sign[i]* (i+2), 1) for i in range(len(dense_bs_sign)) ]
    dense_bs = [ np.random.normal(s * 10, 1) for s in dense_bs_sign ]

    yc = np.dot(xc, np.array(dense_bs)) #+ errors1     # y for conum_treatedrol group 
    
    treatment_eff_coef = np.random.normal( 1.5, 0.15, size=num_cov_important)
    treatment_effect = np.dot(xt, treatment_eff_coef) 
    
    second = construct_sec_order(xt[:,:5])
    treatment_eff_sec = np.sum(second, axis=1)
    
    yt = np.dot(xt, np.array(dense_bs)) + treatment_effect + treatment_eff_sec #+ errors2    # y for treated group 

    xc2 = np.random.binomial(1, control_m, size=(num_control, num_covs_unimportant))   # unimportant covariates for control group
    xt2 = np.random.binomial(1, treated_m, size=(num_treated, num_covs_unimportant))   # unimportant covariates for treated group
        
    df1 = pd.DataFrame(np.hstack([xc, xc2]), 
                       columns = range(num_cov_important + num_covs_unimportant))
    df1['outcome'] = yc
    df1['treated'] = 0

    df2 = pd.DataFrame(np.hstack([xt, xt2]), 
                       columns = range(num_cov_important + num_covs_unimportant ) ) 
    df2['outcome'] = yt
    df2['treated'] = 1

    df = pd.concat([df1,df2])
    df['matched'] = 0
  
    return df, dense_bs, treatment_eff_coef

# In[53]:

def match(df, covs, covs_max_list, treatment_indicator_col = 'treated', match_indicator_col = 'matched'):
    covs = list(covs)
    covs_max_list = list(covs_max_list)
    
    # this function takes a dataframe, a set of covariates to match on, 
    # the treatment indicator column and the matched indicator column.
    # it returns the array indicating whether each unit is matched (the first return value), 
    # and a list of indices for the matched units (the second return value)
    
    arr_slice_wo_t = df[covs].values # the covariates values as a matrix
    arr_slice_w_t = df[ covs + [treatment_indicator_col] ].values # the covariate values together with the treatment indicator as a matrix
        
    lidx_wo_t = np.dot( arr_slice_wo_t, np.array([ covs_max_list[i]**(len(covs_max_list) - 1 - i) for i in range(len(covs_max_list))]) ) # matrix multiplication, get a unique number for each unit
    lidx_w_t = np.dot( arr_slice_w_t, np.array([ covs_max_list[i]**(len(covs_max_list) - i) for i in range(len(covs_max_list))] +                                               [1]
                                              ) ) # matrix multiplication, get a unique number for each unit with treatment indicator
        
    _, unqtags_wo_t, counts_wo_t = np.unique(lidx_wo_t, return_inverse=True, return_counts=True) # count how many times each number appears
    _, unqtags_w_t, counts_w_t = np.unique(lidx_w_t, return_inverse=True, return_counts=True) # count how many times each number appears (with treatment indicator)
    
    match_indicator = ~(counts_w_t[unqtags_w_t] == counts_wo_t[unqtags_wo_t]) # a unit is matched if and only if the counts don't agree
        
    return match_indicator, lidx_wo_t[match_indicator]

# In[54]:

# match_quality, the larger the better
def match_quality(df, holdout, covs_subset, match_indicator, ridge_reg = 0.1, tradeoff = 0.1):
    covs_subset = list(covs_subset)

    s = time.time()
    num_control = len(df[df['treated']==0]) # how many control units that are unmatched (recall matched units are removed from the data frame)
    num_treated = len(df[df['treated']==1]) # how many treated units that are unmatched (recall matched units are removed from the data frame)
    
    num_control_matched = np.sum(( match_indicator ) & (df['treated']==0) ) # how many control units that are matched on this level
    num_treated_matched = np.sum(( match_indicator ) & (df['treated']==1) ) # how many treated units that are matched on this level
        
    time_BF = time.time() - s
    
    # -- below is the regression part for PE
    s = time.time()
    ridge_c = Ridge(alpha=ridge_reg) 
    ridge_t = Ridge(alpha=ridge_reg) 
    #tree_c = DecisionTreeRegressor(max_depth=8, random_state=0)
    #tree_t = DecisionTreeRegressor(max_depth=8, random_state=0)
        
    n_mse_t = np.mean(cross_val_score(ridge_t, holdout[holdout['treated']==1][covs_subset], 
                                holdout[holdout['treated']==1]['outcome'] , scoring = 'neg_mean_squared_error' ) )
        
    n_mse_c = np.mean(cross_val_score(ridge_c, holdout[holdout['treated']==0][covs_subset], 
                                holdout[holdout['treated']==0]['outcome'] , scoring = 'neg_mean_squared_error' ) )
    
    #n_mse_t = np.mean(cross_val_score(tree_t, holdout[holdout['treated']==1][covs_subset], 
    #                            holdout[holdout['treated']==1]['outcome'] , scoring = 'neg_mean_squared_error' ) )
        
    #n_mse_c = np.mean(cross_val_score(tree_c, holdout[holdout['treated']==0][covs_subset], 
    #                            holdout[holdout['treated']==0]['outcome'] , scoring = 'neg_mean_squared_error' ) )
    
    time_PE = time.time() - s
    # -- above is the regression part for PE
    
    # -- below is the level-wise MQ
    return  (tradeoff * ( float(num_control_matched)/num_control + float(num_treated_matched)/num_treated ) +             ( n_mse_t + n_mse_c ) , time_PE , time_BF ) 
    # -- above is the level-wise MQ
    
    #return (balance_reg * (num_treated_matched + num_control_matched) * ( float(num_control_matched)/num_control +\
    #                       float(num_treated_matched)/num_treated ) +\
    #         (num_treated_matched + num_control_matched) * ( n_mse_t  + n_mse_c ) , time_PE , time_BF ) 
    
# In[55]:

def get_CATE_bit(df, match_indicator, index):
    d = df[ match_indicator ]
    if index is None: # when index == None, nothing is matched
        return None
    d.loc[:,'grp_id'] = index
    res = d.groupby(['grp_id', 'treated'])['outcome'].aggregate([np.size, np.mean]) # we do a groupby to get the statistics
    return res

# In[56]:

def recover_covs(d, covs, covs_max_list, binary = True):
    covs = list(covs)
    covs_max_list = list(covs_max_list)

    ind = d.index.get_level_values(0)
    ind = [ num2vec(ind[i], covs_max_list) for i in range(len(ind)) if i%2==0]

    df = pd.DataFrame(ind, columns=covs ).astype(int)

    mean_list = list(d['mean'])
    size_list = list(d['size'])
        
    effect_list = [mean_list[2*i+1] - mean_list[2*i] for i in range(len(mean_list)/2) ]
    df.loc[:,'effect'] = effect_list
    df.loc[:,'size'] = [size_list[2*i+1] + size_list[2*i] for i in range(len(size_list)/2) ]
    
    return df

def cleanup_result(res_all):
    res = []
    for i in range(len(res_all)):
        r = res_all[i]
        if not r[1] is None:
            res.append(recover_covs( r[1], r[0][0], r[0][1] ) )
    return res

def num2vec(num, covs_max_list):
    res = []
    for i in range(len(covs_max_list)):
        num_i = num/covs_max_list[i]**(len(covs_max_list)-1-i)
        res.append(num_i)
        
        if (num_i == 0) & (num%covs_max_list[i]**(len(covs_max_list)-1-i) == 0):
            res = res + [0]*(len(covs_max_list)-1-i)
            break
        num = num - num_i* covs_max_list[i]**(len(covs_max_list)-1-i)
    return res


# In[57]:

def run_bit(df, holdout, covs, covs_max_list, tradeoff_param = 0.1):
    s_start = time.time()

    covs = list(covs)
    covs_max_list = list(covs_max_list)

    constant_list = ['outcome', 'treated']
    
    covs_dropped = []
    cur_covs = covs[:]
    cur_covs_max_list = covs_max_list[:]

    timings = [0]*5 # first entry - match (matrix multiplication and value counting and comparison), 
                    # second entry - regression (compute PE),
                    # third entry - compute BF, fourth entry - keep track of CATE,
                    # fifth entry - update dataframe (remove matched units)
    
    level = 1
    print("level ", str(level))
    s = time.time()
    match_indicator, index = match(df, cur_covs, covs_max_list) # match without dropping anything
    timings[0] = timings[0] + time.time() - s
    
    s = time.time()
    res = get_CATE_bit(df, match_indicator, index) # get the CATEs without dropping anything
    timings[3] = timings[3] + time.time() - s
    
    matching_res = [[( cur_covs, cur_covs_max_list, None, match_indicator, index), res]] # result on first level, None says nothing is dropped
    
    s = time.time()
    df = df[~match_indicator][ cur_covs + constant_list ] # remove matched units
    timings[4] = timings[4] + time.time() - s
    
    level_scores = []
    
    while len(cur_covs)>1:
        
        #print(cur_covs)
        
        best_score = np.inf
        level += 1
        print("level ", str(level))
        matching_result_tmp = []
        
        if (np.sum(df['treated'] == 0) == 0 ) | (np.sum(df['treated'] == 1) == 0 ): # the early stopping condition
            print('no more matches')
            break
        
        for i in range(len(cur_covs)):
            
            cur_covs_no_c = cur_covs[:i] + cur_covs[i+1:]
            
            cur_covs_max_list_no_c = cur_covs_max_list[:i] + cur_covs_max_list[i+1:]
            
            s = time.time()
            match_indicator, index = match(df, cur_covs_no_c, cur_covs_max_list_no_c)
            timings[0] = timings[0] + time.time() - s 
            
            score, time_PE, time_BF = match_quality(df, holdout, cur_covs_no_c, match_indicator, tradeoff=tradeoff_param)
            timings[1] = timings[1] + time_PE 
            timings[2] = timings[2] + time_BF 
                                    
            matching_result_tmp.append( (cur_covs_no_c, cur_covs_max_list_no_c, score, match_indicator, index) )
        
        best_res = max(matching_result_tmp, key=itemgetter(2)) # use the one with largest MQ as the one to drop
        
        level_scores.append(max( [t[2] for t in matching_result_tmp] ))
        
        del matching_result_tmp
        
        new_matching_res = get_CATE_bit(df, best_res[-2], best_res[-1])
        
        cur_covs = best_res[0] 
        cur_covs_max_list = best_res[1]
        matching_res.append([best_res, new_matching_res])
        
        s = time.time()
        df = df[~ best_res[-2] ]
        timings[4] = timings[4] + time.time() - s
    
    s_end = time.time()

    print("time:", s_end - s_start)    
    return (timings, matching_res, level_scores )


if __name__ == '__main__':

    # store data in Pandas dataframe
    # call the 'run' function to run the algorithm. the first argument is the dataframe of interest, 
    # the second argument is the holdout dataframe, the third argument is the list of covariates,
    # the fourth argument is the number of choices each covariate has (say, if the ccovariate is binary, this number here should be 2)
    # and the fifth argument is the trade-off parameter. Larger tradeoff parameter puts more weight on matching more data, 
    # while smaller tradeoff parameter puts more weight on predicting the result correctly. 
    # the result is saved in a pickle file named as "FLAME-bit-result"

    
    #### IMPORTANT NOTE: make sure to reorder the columns so that the covariate A is on the left of covariate B is A has more choices than B.
    ####                 For example, if your covariates A, B, C are ternary, binary, and quaternary respectively. They should be reordered from left to right: C, A, B.
    #### IMPORTANT NOTE: make sure to name the columns by numbers, say, if you have 3 covariates, name them to be 0,1,2 from left to right

    ## below is an example
    df,_,_ = data_generation(2500, 2500, 1, 9)
    holdout,_,_ = data_generation(2500, 2500, 1, 9)

    res = run_bit(df, holdout, range(10), [2]*10, tradeoff_param = 0.1)

    #pickle.dump(res, open('FLAME-bit-result', 'wb'))
    ## above is an example