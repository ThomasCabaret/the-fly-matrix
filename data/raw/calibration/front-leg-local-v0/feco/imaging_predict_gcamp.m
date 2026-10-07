function y_conv = imaging_predict_gcamp(x,sr,model_type,threshold)
%IMAGING_PREDICT_GCAMP predicts calcium signals based on behavioral signals   
%
%   y_conv = IMAGING_PREDICT_GCAMP(x,sr,model_type,threshold) predicts calcium signals based on behavioral signals.
%   
%   x          = time course of behavioral signal   
%   sr         = sampling rate
%   model_type = type of activation function
%   threshold  = thresholds for some activation functions  

% Author: Chris J. Dallmann 
% Affiliation: University of Wuerzburg
% Last revision: 13-May-2024

% ------------- BEGIN CODE -------------

if ~ismember(model_type,{...
        'claw', ...
        'hook_flex', ...
        'hook_ext', ...
        'club', ...
        '9A',...
        'web'})
    error('Unknown model')
end

if size(x,2)>size(x,1)
    x = x';
end

if size(x,2)>1
    x2 = x(:,2);
    x(:,2) = [];
end

% Calculate derivative 
dx = diff(x).*sr;
dx = [dx(1);dx];

% Set time vector
t = linspace(0,size(x,1)./sr,size(x,1))';

% Apply activation function
switch model_type
    case 'claw'
        x = x-80;
        % Coefficients fitted to normalized calcium data from Mamiya et al.
        % (2018)
        coeff = [-4.28350195279596e-09, -3.08701145496934e-07, 0.000123726627502515, 0.000474757347677466, -0.0357758464550021];
        y = coeff(1).*x.^4 + coeff(2).*x.^3 + coeff(3).*x.^2 + coeff(4).*x + coeff(5);

    case 'hook_flex'
        for i = 1:numel(dx)
            if dx(i)>=threshold
                y(i,1) = 0;
            else
                y(i,1) = 1;
            end
        end
             
    case 'hook_ext'
        for i = 1:numel(dx)
            if dx(i)<=threshold
                y(i,1) = 0;
            else
                y(i,1) = 1;
            end
        end
                
    case 'club'
        for i = 1:numel(dx)
            if dx(i)>threshold
                y(i,1) = 1;
            elseif dx(i)<-threshold
                y(i,1) = 1;
            else
                y(i,1) = 0;
            end
        end
     
    case '9A'
        dx(x2==1) = 0;
        for i = 1:numel(dx)
            if dx(i)>threshold
                y(i,1) = 1;
            elseif dx(i)<-threshold
                y(i,1) = 1;
            else
                y(i,1) = 0;
            end
        end

    case 'web'
        y = x;
end

% Generate GCaMP function
tau_on = 0.03; 
tau_off = 0.30; 
gcamp = exp(-t./tau_off)-exp(-t./tau_on);
gcamp = gcamp/sum(gcamp);

% Convolve activation with GCaMP function
y_conv = conv(y, gcamp); 
y_conv = y_conv(1:numel(t),:);

end


