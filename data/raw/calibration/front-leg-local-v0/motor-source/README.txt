Data and figure creation scripts for
eLife 2020;9:e56754 DOI: 10.7554/eLife.56754

Data files are in .zip archives, whithin the folder structure. Each .zip folder contains data in .mat native MATLAB format, scripts are matlab (.m) scripts.

Contents:
Azevedo_2020_Records - Directory of scripts to create each figure panel. "Figure creation scripts.xlsx" provides a table to indicate which top level Dataset script to run to generate each panel, as well as the specific lower level script. Each top level script (e.g. Dataset1_LegCaImaging_MHCDriver) first creates a matlab table datastructure of individual cells/flies. Sections are then labeled to show which panels the specific low level script create.

Datasets 1, 2, 3 - Data from each fly/cell can be found in separatae .zip files. Due to constraints on file transfer, the user will have to recreate the following directory structure: <yymmdd>/<yymmdd_Fx_Cy>, e.g. 171101/171101_F1_C1,  where Fx indicates the xth fly of the day, and Cy indicates the yth cell for that fly. Each .zip file contains the data from a single cell on a particular day. All cells from a particular day should be placed in the directory for that date, the scripts will expect this structure. For each cell, <yymmdd_Fx_Cy>, the data for a particular trial is contained in a .mat file  typically the presentation of one instance of a stimulus or protocol. Naming convention is <ProtocolName>_Raw_<CellID>_<Trial number>.mat. The parameters of the stimulus are stored in the file, together with recorded inputs in natural units (pA, mV, etc). Spike detection and tracking of the force probe have been included for relevant trials. A notes file accompanies each fly/cell and gives the overview of the experiment. Videos of the leg movements and probe have not been included for space, but are available upon request. 

To easily view individual trials, load a trial into matlab by dragging it into the workspace. To run the scripts, first fork copies of the following repositories and place the code on your matlab path:
https://github.com/tony-azevedo/FlyAnalysis
https://github.com/tony-azevedo/FlySound
https://github.com/tony-azevedo/Matlab-Analysis
Top level scripts are typically run 1 section at a time in matlab. Note: hardcoded dirctory locations will have to be changed.

The xlsx, MN anatomy confocal measurements.xlsx, shows each measurement taken from confocal stacks of fills from each motor neuron type, shown in Figure 3A.
