#!/usr/bin/env python
'''
Command to Label

Usage: command2label [--dockerfile <Dockerfile>] <command>...

Prints the org.nrg.commands LABEL for the given command JSON files. With --dockerfile,
replaces any existing org.nrg.commands LABEL in that Dockerfile instead (appending it if
there is none), so running this repeatedly never duplicates the label.
'''


import argparse
import json

LABEL_PREFIX = 'LABEL org.nrg.commands='

parser = argparse.ArgumentParser(description='Convert command JSON files to a Dockerfile LABEL')
parser.add_argument('--dockerfile', help='Dockerfile whose org.nrg.commands LABEL should be replaced')
parser.add_argument('commands', nargs='+', help='Command JSON files')
args = parser.parse_args()

commandStrList = []
for commandFile in args.commands:
    with open(commandFile) as f:
        commandObj = json.load(f)
    commandStr = json.dumps(commandObj) \
                        .replace('"', r'\"') \
                        .replace('$', r'\$')
    commandStrList.append(commandStr)

label = 'LABEL org.nrg.commands="[{}]"'.format(', \\\n\t'.join(commandStrList))

if args.dockerfile is None:
    print(label)
else:
    with open(args.dockerfile) as f:
        lines = f.read().splitlines()

    # Drop every existing org.nrg.commands LABEL, including its backslash-continued lines
    keptLines = []
    inLabel = False
    for line in lines:
        if line.startswith(LABEL_PREFIX):
            inLabel = True
        if not inLabel:
            keptLines.append(line)
        elif not line.rstrip().endswith('\\'):
            inLabel = False

    while keptLines and not keptLines[-1].strip():
        keptLines.pop()

    with open(args.dockerfile, 'w') as f:
        f.write('\n'.join(keptLines + [label]) + '\n')
