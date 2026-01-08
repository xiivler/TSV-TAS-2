# TSV-TAS-2
TSV-TAS-2 is the latest compiler of TSV-TAS, a script format for TASing Super Mario Odyssey. Thanks to PlacidMink for contributions to the project.

```tsv-tas.py``` takes a script in the TSV-TAS format and compiles it into either a binary file for LunaKit or a nx-TAS file for smo-practice.

```nx-tas-to-tsv-tas.py``` converts nx-TAS scripts into TSV-TAS scripts.

## Writing TSV-TAS Scripts
Read the documentation [here](https://docs.google.com/document/d/1vW-swF3k96YxaIJqXbtRXbQ54mKKgeWfPFlW2hYBa_Q/edit?usp=sharing).

## Running the Compiler
First, make sure you have Python 3 installed.

In the command line, navigate to the ```TSV-TAS-2``` directory and enter ```python3 tsv-tas.py [options] [path to TSV or CSV file] [path to output file]```.

By default, the output file will be a binary file that can be used with LunaKit.

### Options
The following options can be used on the command line to customize the output:

```-f``` FTP: Sends the output file to the directory ```SMO/tas/scripts``` on your Switch's SD card via FTP for use with LunaKit

```-n``` nx-TAS: Generates a nx-TAS script file (for use with smo-practice) instead of a binary script file

```-e``` Skip empty (nx-TAS only): Skips frames with no inputs in the output file to make the file smaller (currently only supported for compiling nx-TAS scripts)

```-l``` Loop: Allows you to press enter to keep re-generating the script instead of rerunning the command

```-d``` Debug: Generates a CSV file in the ```TSV-TAS-2``` directory showing how the program interprets each frame of your script for debugging purposes

You can mix and match as many of the following options as you would like by writing all the letters after one hyphen. For example, you can run ```python3 tsv-tas.py -ne tas.tsv tas.txt``` to generate an nx-TAS file ```tas.txt``` that skips empty frames.

### FTP Setup
If you would like to send ouptut files to your Switch via FTP, first enter your FTP server configuration information in ```ftp_config.json```. Then, run the command ```python3 tsv-tas.py -f [path to TSV file] [name of output file]``` to send the file to the Switch's SD card.

## Converting nx-TAS to TSV-TAS
To convert an nx-TAS script to a TSV-TAS script, in the command line, navigate to the ```TSV-TAS-2``` directory and enter ```python3 nx-tas-to-tsv-tas.py [path to nx-TAS file] [path to output file]```.
