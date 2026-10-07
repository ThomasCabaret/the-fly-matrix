% IMAGING_FIT_ACTIVATION_FUNCTION.m fits the activation functions used in Dallmann et al. (2025)
% 
% Files required: 
%    *_Mamiya2018.parquet
%
% Functions/toolboxes required:
%    imaging_predict_gcamp.m
%    imaging_poly_fun.m
%    Optimization Toolbox
% 
% See also imaging_predict_gcamp.m, imaging_poly_fun.m

% Author: Chris J. Dallmann 
% Affiliation: University of Wuerzburg
% Last revision: 29-July-2025

% ------------- BEGIN CODE -------------

clear

% Settings
settings.parquet_file = 'club_magnet_Mamiya2018';
settings.model_activation_function = 'club';
settings.roi = {'L1_x'}; % {'L1_x','L1_y','L1_z'} or {'L1_medial'} or {'L1_x'};

settings.n_frames_pad = 1000; % If changed, update poly_fun

% Load parquet file 
[parent_folder, ~] = fileparts(cd);
data = parquetread([parent_folder,'\data\',settings.parquet_file,'.parquet']);

settings.sampling_rate = ceil(1/data.time(2)); 

% Select frames
frames = contains(data.roi,settings.roi) ... 
         & data.analyze == 1;

trials = unique(data.trial(frames),'stable')'; % Note: Without 'stable', unique sorts

% Normalize calcium signals
data.calcium_norm = data.calcium./max(data.calcium(frames));


%% Fit activation function
if strcmp(settings.model_activation_function,'claw')  
    % For claw, fit polynomial model across trials
    coeff_0 = [0, 0, 0, 0, 0]; 
    x = data.L1C_flex(frames)-90; % Remove offset
    y = data.calcium_norm(frames);

    % Set optimization options
    options = optimset('Display','iter','FunValCheck','on', ...
                       'MaxFunEvals',Inf,'MaxIter',Inf, ...
                       'TolFun',1e-6,'TolX',1e-6);

    % Nonlinear least-squares optimization
    [coeff, ~, ~, ~, ~] = lsqcurvefit(@imaging_poly_fun, coeff_0, x, y, [], [], options);

    model.coeff = coeff;
    model.fitted = imaging_poly_fun(coeff,x);

    clearvars coeff_0 x y options coeff 

else
    % For hook and club, use fixed-kernel model 
    if strcmp(settings.model_activation_function,'hook_flex')  
        settings.model_parameters = -5; 
    elseif strcmp(settings.model_activation_function,'club')
        settings.model_parameters = 5;
    end

    % To avoid edge artifacts from concatenation of trials,
    % calculate prediction per trial, then fit across trials. 
    y_hat = [];    
    for iTrial = 1:numel(trials)
        data_trial.frames = data.trial == trials(iTrial) & frames;
        data_trial.y = data.calcium_norm(data_trial.frames);
        data_trial.x = data.L1C_flex(data_trial.frames);   
           
        data_trial.y_hat = imaging_predict_gcamp( ...
            data_trial.x, ...
            settings.sampling_rate, ...
            settings.model_activation_function, ...
            settings.model_parameters);
    
        y_hat = [y_hat; data_trial.y_hat];
        
        clearvars data_trial   
    end
    clearvars iTrial

    % Fit slope and intercept across trials 
    y = data.calcium_norm(frames);
    mdl = fitlm(y_hat,y);
    model.fitted = mdl.Fitted;

    clearvars y y_hat mdl 
end


%% Plot activation function (without convolution)
if strcmp(settings.model_activation_function,'claw')
    x = (-90:90)';
    y_hat = model.coeff(1).*x.^4 ...
        + model.coeff(2).*x.^3 ... 
        + model.coeff(3).*x.^2 ...
        + model.coeff(4).*x ...
        + model.coeff(5);
elseif strcmp(settings.model_activation_function,'hook_flex')
    x = (-100:100)';
    y_hat = zeros(numel(x),1); 
    y_hat(x<-5) = 1; 
elseif strcmp(settings.model_activation_function,'club')
    x = (-100:100)';
    y_hat = zeros(numel(x),1); 
    y_hat(x<-5) = 1;
    y_hat(x>5) = 1;
end
figure
plot(x, y_hat, 'k')
ylim([-.1,1.1])
ylabel('Activation')
set(gca,'Color','none')


%% Evaluate model per trial
frames_selected = frames;
frames_selected(frames==0) = [];
data_selected = data;
data_selected(frames==0,:) = []; % This way, data_selected is the same size as model.fitted

r0 = []; 
y_hat = nan(460,numel(trials));
calcium = nan(460,numel(trials));
L1C_flex = nan(460,numel(trials));
stimulus_type = {};
roi = {};
% Loop over trials
for iTrial = 1:numel(trials)
    data_trial.frames = data_selected.trial == trials(iTrial);
     
    data_trial.y_hat = model.fitted(data_trial.frames);
    data_trial.calcium_norm = data_selected.calcium_norm(data_trial.frames);
    
    % Cross correlation
    [data_trial.r,data_trial.lags] = xcorr(data_trial.calcium_norm,data_trial.y_hat,'coeff');
    r0 = [r0; data_trial.r(data_trial.lags==0)];
           
    % Store data per trial
    data_trial.n_frames = sum(data_trial.frames);
    y_hat(1:data_trial.n_frames, iTrial) = data_trial.y_hat;
    calcium(1:data_trial.n_frames, iTrial) = data_trial.calcium_norm;
    L1C_flex(1:data_trial.n_frames, iTrial) = data_selected.L1C_flex(data_trial.frames);
    stimulus_type{iTrial} = data_selected.stimulus_type{data_trial.frames};
    roi{iTrial} = data_selected.roi{data_trial.frames};
        
    clearvars data_trial   
end
clearvars iTrial 


%% Plot time courses for a specific stimulus
stimulus_to_plot = 'ramp_hold_ext_first'; % 'ramp_hold_flex_first' or 'ramp_hold_ext_first' 
if contains(settings.parquet_file,'claw') || contains(settings.parquet_file,'club')
    roi_to_plot = 'L1_x';
else  
    roi_to_plot = 'L1_medial';
end

trials_to_plot = contains(stimulus_type,stimulus_to_plot) ...
                 & contains(roi,roi_to_plot);

% Plot mean of animal means and standard error of the mean
figure
subplot(311)
    y = L1C_flex(:,trials_to_plot);
    hold on
    plot(nanmean(y,2),'k')
    plot(nanmean(y,2) + nanstd(y,0,2)/sqrt(sum(trials_to_plot)),'k')
    plot(nanmean(y,2) - nanstd(y,0,2)/sqrt(sum(trials_to_plot)),'k')
    hold off
    ylim([0,190])
    ylabel('L1C_flex','Interpreter','none','Rotation',0)
    set(gca,'xticklabel','','color','none','ytick',0:90:180)
subplot(312)
    y = calcium(:,trials_to_plot);
    hold on
    plot(nanmean(y,2),'k')
    plot(nanmean(y,2) + nanstd(y,0,2)/sqrt(sum(trials_to_plot)),'k')
    plot(nanmean(y,2) - nanstd(y,0,2)/sqrt(sum(trials_to_plot)),'k')
    hold off
    ylabel('calcium_norm','Interpreter','none','Rotation',0)
    set(gca,'xticklabel','','ylim',[-.1,1.1],'ytick',[0,1],'color','none')
subplot(313)
    y = y_hat(:,trials_to_plot);
    hold on
    plot(nanmean(y,2),'k')
    plot(nanmean(y,2) + nanstd(y,0,2)/sqrt(sum(trials_to_plot)),'k')
    plot(nanmean(y,2) - nanstd(y,0,2)/sqrt(sum(trials_to_plot)),'k')
    hold off
    ylabel('fitted_calcium_norm','Interpreter','none','Rotation',0)
    set(gca,'ylim',[-.1,1.1],'ytick',[0,1],'color','none')


%% Plot cross-correlation across stimuli
trials_to_plot = contains(roi,roi_to_plot);

f = figure;
f.Position = [500,500,200,400];
hold on
h = scatter(ones(sum(trials_to_plot),1),r0(trials_to_plot), ...
    'k','filled', ...
    'jitter','on','jitteramount',.2, ...
    'MarkerEdgeColor','none','MarkerFaceAlpha',.5);
plot([.8,1.2], [median(r0(trials_to_plot)),median(r0(trials_to_plot))],'k')
hold off
ylim([-.1,1.1])
xlim([0,2])
hold off
ylabel('Cross-correlation (r)')
set(gca,'XTick',[],'Color','none')

disp(['Median r0=', num2str(median(r0(trials_to_plot)))])
disp(['Number of trials: ', num2str(length(r0(trials_to_plot)))])
disp(['Number of animals: ', num2str(length(unique(data.animal_id(contains(data.roi,roi_to_plot)))))])  
