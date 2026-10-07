function F = imaging_poly_fun(coeff,x)
%IMAGING_POLY_FUN contains code for a polynomial function   

% Author: Chris J. Dallmann 
% Affiliation: University of Wuerzburg
% Last revision: 13-May-2024

% ------------- BEGIN CODE -------------

pad = 1000;
sampling_rate = 8.01;
x = [repmat(x(1),pad,1); x]; 
    
F = coeff(1).*x.^4 + coeff(2).*x.^3 + coeff(3).*x.^2 + coeff(4).*x + coeff(5);

t = linspace(0,size(x,1)./sampling_rate,size(x,1))';
tau_on = 0.03; 
tau_off = 0.30; 
gcamp = exp(-t./tau_off)-exp(-t./tau_on);
gcamp = gcamp/sum(gcamp);

F = conv(F, gcamp); 
F = F(1:numel(t),:);
F(1:pad) = [];

end